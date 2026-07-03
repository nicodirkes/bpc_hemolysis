#!/usr/bin/env nextflow

def toYaml(data) {
    def yb = new groovy.yaml.YamlBuilder()
    yb.call(data)
    return yb.toString()
}

def _nModel() {
    try {
        def cfg = new groovy.yaml.YamlSlurper().parseText(file(params.config_file).text) as Map
        return (cfg.model?.n_workers ?: 1) as int
    } catch (Exception _ignored) { return 1 }
}
def _nCalib() {
    try {
        def cfg = new groovy.yaml.YamlSlurper().parseText(file(params.config_file).text) as Map
        return (cfg.calibration?.n_workers ?: 1) as int
    } catch (Exception _ignored) { return 1 }
}

def _workflowMeta(f) {
    def cfg = new groovy.yaml.YamlSlurper().parseText(f.text) as Map
    def key = cfg.containsKey('experiment_hash') ? cfg.experiment_hash : workflow.sessionId
    def bundle_name = "${cfg.species}_${cfg.model.name}_${key}".toString()
    return [key, cfg, bundle_name, toYaml(cfg)]
}

def _addPort(row) {
    return [row[0], row[1], row[2], row[3], row[4], row[5], Math.abs(new Random().nextInt() % (31767 - 16384)) + 16384]
}

def _modelInputs(row) {
    Thread.sleep(2000)
    return [row[0], row[1].model.name, row[4], row[6], row[5], row[1].model.get('n_workers', 1), row[1].model.get('use_julia', false)]
}

def _mcmcInputs(row) {
    Thread.sleep(2000)
    return [row[0], row[3], row[4], row[5], row[1].calibration.get('n_workers', 1)]
}

workflow bpc_hemolysis {

    take:
    config_file
    output_base_dir

    main:
    // Single source of truth: all per-experiment metadata derived once from the config
    workflow_meta = config_file.map { f -> _workflowMeta(f) }
    // workflow_meta: [key, cfg, bundle_name, params_yaml]

    PULL_DATA_COSCINE(
        file("$moduleDir/pull_data/.token.txt"),
        "showmehow_usecase5",
        "Field Data"
    )

    PREPROCESS_DATA(
        file("$moduleDir/preprocessing/preprocessing.py"),
        "data_ding_",
        workflow_meta.map { row -> row[1].species },
        PULL_DATA_COSCINE.out,
        workflow_meta.map { row -> row[0] }
    )

    SETUP_UM_IPC(
        PREPROCESS_DATA.out.done
    )

    // Join workflow_meta with [key, data] and [key, comm] — guaranteed per-experiment pairing.
    experiment_config = workflow_meta
        .join(PREPROCESS_DATA.out.data)
        .join(SETUP_UM_IPC.out)
        .combine(SETUP_UM_IPC.out.count())
        .map { row -> row[0..-2] }
    // experiment_config: [key, cfg, bundle_name, params_yaml, data, comm]

    // experiment_config items: [key, cfg, bundle_name, params_yaml, data, comm]
    // Fan out to model and mcmc channels via separate maps (multiMap uses labeled-expression
    // DSL that is broken in Nextflow 26.04).
    experiment = experiment_config.map { row -> _addPort(row) }
    // experiment items: [key, cfg, bundle_name, params_yaml, data, comm, port]

    model_inputs = experiment.map { row -> _modelInputs(row) }
    // model_inputs items: [key, name, data, port, comm, n_workers, use_julia]

    mcmc_inputs = experiment.map { row -> _mcmcInputs(row) }
    // mcmc_inputs items: [key, params_yaml, data, comm, n_workers]

    SERVE_MODEL_JL(
        file("$moduleDir/model_julia/IH_model_server.jl"),
        file("$moduleDir/model_julia/src"),
        model_inputs
            .filter { row -> row[6] }
            .map { row -> [row[0], row[1], row[2], row[3], row[4]] }
    )

    SERVE_MODEL_PY(
        file("$moduleDir/model/IH_model_server.py"),
        file("$moduleDir/model/src"),
        model_inputs
            .filter { row -> !row[6] }
            .map { row -> [row[0], row[1], row[2], row[3], row[4], row[5]] }
    )

    MCMC_CALIBRATION(
        file("$moduleDir/mcmc/calibrate_emcee.py"),
        mcmc_inputs
    )

    RUN_DIAGNOSTICS(
        file("$moduleDir/diagnostics/run_diagnostics.py"),
        MCMC_CALIBRATION.out.mcmc_idata,
        "diagnostics"
    )

    // Join workflow_meta with all keyed outputs — guaranteed per-experiment pairing into BUNDLE_OUTPUTS
    bundle_inputs = workflow_meta
        .join(MCMC_CALIBRATION.out.mcmc_output)
        .join(MCMC_CALIBRATION.out.mcmc_corner_plot)
        .join(MCMC_CALIBRATION.out.mcmc_trace)
        .join(MCMC_CALIBRATION.out.mcmc_idata)
        .join(RUN_DIAGNOSTICS.out)
    // bundle_inputs: [key, cfg, bundle_name, params_yaml, mcmc_output, mcmc_corner_plot, mcmc_trace, mcmc_idata, diagnostics]

    BUNDLE_OUTPUTS(
        output_base_dir,
        bundle_inputs.map { row -> row[2] },
        bundle_inputs.map { row -> row[3] },
        bundle_inputs.map { row -> row[4] },
        bundle_inputs.map { row -> row[5] },
        bundle_inputs.map { row -> row[6] },
        bundle_inputs.map { row -> row[7] },
        bundle_inputs.map { row -> row[8] }
    )

    GENERATE_REPORT(
        file("$moduleDir/report/generate_report.py"),
        output_base_dir,
        BUNDLE_OUTPUTS.out.bundle_dir
    )

    emit:
    bundle = BUNDLE_OUTPUTS.out.bundle_dir
}



process PULL_DATA_COSCINE {
    conda "$moduleDir/pull_data/environment.yml"
    publishDir "$moduleDir/outputs", mode: 'copy'
    
    input:
      path token_file
      val project_name
      val resource_name

    output:
      path "pulled_data"

    script:
        """
        #!/usr/bin/env python3
        import coscine

        # Read access token and setup client
        with open("$token_file", "rt") as fp:
	        token = fp.read()
        client = coscine.ApiClient(token)

        # Download the data
        resource = client.project("$project_name").resource("$resource_name")
        # resource = client.project("showmehow_usecase5").resource("Field Data")
        for file in resource.files():
            file.download(path="./pulled_data/")

        """

}

process PREPROCESS_DATA{
    conda "$moduleDir/preprocessing/environment.yml"

    input:
        file script
        val prefix
        val species
        path input
        val key

    output:
        tuple val(key), path("${prefix}${species}_processed.csv"), emit: data
        tuple val(key), val(true), emit: done

    script:
    """
    python3 preprocessing.py $species --prefix $prefix --indir $input
    """
}

process SETUP_UM_IPC {
    input:
    tuple val(key), val(ready)

    output:
    tuple val(key), path("comm")

    script:
    """
    mkdir comm
    mkdir comm/model_info
    mkdir comm/uq_info
    mkdir comm/umbridge_port
    """
}

process SERVE_MODEL_PY {
    conda "$moduleDir/model/environment.yml"
    cache 'lenient'
    errorStrategy 'retry'
    maxRetries 3
    cpus { _nModel() }

    input:
    path script
    path src
    tuple val(key), val(name), path(data), val(umbridge_port), path(um_highway), val(n_workers)

    script:
    """
    #!/bin/bash
    UMBRIDGE_PORT=${umbridge_port+100*(task.attempt-1)}

    # Abort if port already used (success means something is listening)
    if bash -c "echo > /dev/tcp/localhost/\$UMBRIDGE_PORT" 2>/dev/null; then
        echo "Port \$UMBRIDGE_PORT already in use"
        exit 1
    fi

    # Start model server
    python ${script} --name ${name} --data ${data} --port \$UMBRIDGE_PORT --n_workers ${n_workers} &
    SERVER_PID=\$!
    trap 'kill \$SERVER_PID 2>/dev/null || true; rm -f $um_highway/model_info/READY $um_highway/umbridge_port/* $um_highway/uq_info/DONE' EXIT INT TERM
    echo "Model Server PID: \$SERVER_PID (trying port \$UMBRIDGE_PORT)"

    # Wait for model server to start 
    while ! bash -c "echo > /dev/tcp/localhost/\$UMBRIDGE_PORT" 2>/dev/null; do
        sleep 1
    done

    touch $um_highway/model_info/READY 
    echo "Model ${name} ready" > $um_highway/model_info/READY

    touch $um_highway/umbridge_port/\$UMBRIDGE_PORT
    echo "Model server is running on port \$UMBRIDGE_PORT"

    # Monitor the status 
    echo "Waiting for UQ to complete..."
    until [ -e $um_highway/uq_info/DONE ]; do
        sleep 1
    done

    # Stop the model server when the signal is received
    kill \$SERVER_PID 2>/dev/null || true
    echo "Model server on port \$UMBRIDGE_PORT stopped."

    """
}

process SERVE_MODEL_JL {
    container "bpc_hemolysis/model_julia"
    containerOptions "-p ${umbridge_port+100*(task.attempt-1)}:${umbridge_port+100*(task.attempt-1)}"
    // container "file://$moduleDir/model_julia/container.sif"
    cache 'lenient'
    errorStrategy 'retry'
    maxRetries 3

    input:
    path script
    path src
    tuple val(key), val(name), path(data), val(umbridge_port), path(um_highway)

    script:
    """
    #!/bin/bash
    UMBRIDGE_PORT=${umbridge_port+100*(task.attempt-1)}

    # Abort if port already used (success means something is listening)
    if bash -c "echo > /dev/tcp/localhost/\$UMBRIDGE_PORT" 2>/dev/null; then
        echo "Port \$UMBRIDGE_PORT already in use"
        exit 1
    fi

    # Start model server
    julia ${script} --name ${name} --data ${data} --port \$UMBRIDGE_PORT &
    SERVER_PID=\$!
    trap 'kill \$SERVER_PID 2>/dev/null || true; rm -f $um_highway/model_info/READY $um_highway/umbridge_port/* $um_highway/uq_info/DONE' EXIT INT TERM
    echo "Model Server PID: \$SERVER_PID (trying port \$UMBRIDGE_PORT)"

    # Wait for model server to start
    while ! bash -c "echo > /dev/tcp/localhost/\$UMBRIDGE_PORT" 2>/dev/null; do
        sleep 1
    done

    touch $um_highway/model_info/READY
    echo "Model ${name} ready" > $um_highway/model_info/READY

    touch $um_highway/umbridge_port/\$UMBRIDGE_PORT
    echo "Model server is running on port \$UMBRIDGE_PORT"

    # Monitor the status 
    echo "Waiting for UQ to complete..."
    until [ -e $um_highway/uq_info/DONE ]; do
        sleep 1
    done

    # Stop the model server when the signal is received
    kill \$SERVER_PID 2>/dev/null || true
    echo "Model server on port \$UMBRIDGE_PORT stopped."

    """
}

process MCMC_CALIBRATION {
    conda "$moduleDir/mcmc/environment.yml"
    cache 'lenient'
    cpus     { _nCalib() }

    input:
    path script
    tuple val(key), val(params_yaml), path(data), path(um_highway), val(n_workers)

    output:
    tuple val(key), path("mcmc_output.npz"), emit: mcmc_output
    tuple val(key), path("corner_plot.png"), emit: mcmc_corner_plot
    tuple val(key), path("trace.npy"),       emit: mcmc_trace
    tuple val(key), path("mcmc_idata.nc"),   emit: mcmc_idata

    script:
    """
    echo "${params_yaml}" > _params.yml

    echo "Waiting for model server to start..."
    until [ -e $um_highway/model_info/READY ]; do
        sleep 1
    done
    cat $um_highway/model_info/READY

    MODEL_PORT=\$(ls $um_highway/umbridge_port/ | head -n 1)
    echo "Model server is running on port \${MODEL_PORT}"

    python ${script}  --config _params.yml --data ${data} --port \${MODEL_PORT}

    touch $um_highway/uq_info/DONE # signal to stop the model server
    """
}


process RUN_DIAGNOSTICS {
    conda "$moduleDir/diagnostics/environment.yml"

    input:
    path script
    tuple val(key), path(mcmc_idata)
    val outdir

    output:
    tuple val(key), path("${outdir}")

    script:
    """
    #!/bin/bash
    python3 ${script} --idata-path ${mcmc_idata} --output-dir "${outdir}"
    """
}

process BUNDLE_OUTPUTS {

    input:
    val output_base_dir
    val bundle_name
    val params_yaml
    path mcmc_output
    path mcmc_corner_plot
    path mcmc_trace
    path mcmc_idata
    path mcmc_diagnostics

    output:
    path "${bundle_name}", emit: bundle_dir

    script:
    """
    #!/bin/bash
    echo "${params_yaml}" > params.yml

    mkdir "${bundle_name}"

    cp params.yml "${bundle_name}"
    cp ${mcmc_output} "${bundle_name}/"
    cp ${mcmc_corner_plot} "${bundle_name}/"
    cp ${mcmc_trace} "${bundle_name}/"
    cp ${mcmc_idata} "${bundle_name}/"
    cp -r ${mcmc_diagnostics} "${bundle_name}/"

    mkdir -p "${output_base_dir}"
    cp -r "${bundle_name}" "${output_base_dir}/"
    """
}


process GENERATE_REPORT {
    conda "$moduleDir/report/environment.yml"

    input:
    path script
    val output_base_dir
    path bundle_dir

    output:
    path "report.pdf"

    script:
    """
    #!/bin/bash
    python3 ${script} \\
        --bundle-dir ${bundle_dir} \\
        --output report.pdf
    cp report.pdf "${output_base_dir}/${bundle_dir.name}/"
    """
}

workflow {
    bpc_hemolysis(
        Channel.value(file(params.config_file)),
        "$projectDir/outputs".toString()
    )
}