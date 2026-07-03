#!/usr/bin/env nextflow
include { bpc_hemolysis; toYaml } from './main.nf'

workflow {
    config = new groovy.yaml.YamlSlurper().parseText(file(params.config_file).text)

    exp_base_dir  = "$projectDir/outputs/experiments/${workflow.start}_${workflow.sessionId}".toString()
    params_yaml   = toYaml(config)

    experiments = GENERATE_EXPERIMENTS(
        file("$projectDir/experiments/generate_experiments.py"),
        params_yaml
    ).flatten()

    bpc_hemolysis(experiments, exp_base_dir)
}

process GENERATE_EXPERIMENTS {
    conda "$projectDir/experiments/environment.yml"
    publishDir "$projectDir/outputs/experiments/${workflow.start}_${workflow.sessionId}/", mode: 'copy'

    input:
    path script
    val params_yaml

    output:
    path "experiment_*.yml"

    script:
    """
    echo "${params_yaml}" > params.yml
    python3 ${script} params.yml
    """
}
