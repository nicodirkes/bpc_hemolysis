using UMBridge
using CSV
using DataFrames
using ArgParse

include("src/IH_model.jl")

function get_IH_model(
    name::String,
    data::DataFrame
    )

    if name=="IH_powerLaw_stressBased"
        model_func = IH_powerLaw_stressBased
        parameters = 3
    elseif name=="IH_powerLaw_strainBased"
        model_func = IH_powerLaw_strainBased_analytical
        parameters = 3
    elseif name=="IH_powerLaw_strainBased_f1"
        # The trailing f1 = 1/tau is calibrated rather than held at its
        # literature value, so the model takes one parameter more.
        model_func = IH_powerLaw_strainBased_analytical
        parameters = 4
    elseif name=="IH_powerLaw_strainBased_tau"
        # As _f1, but the free parameter is the relaxation time tau = 1/f1.
        model_func = (t_exp, sigma_exp, A, alpha, beta, tau) ->
            IH_powerLaw_strainBased_analytical(t_exp, sigma_exp, A, alpha, beta, 1.0/tau)
        parameters = 4
    elseif name=="IH_poreFormation_strainBased_tau"
        model_func = (t_exp, sigma_exp, h, k, tau) ->
            IH_poreFormation_strainBased_analytical_binomial(t_exp, sigma_exp, h, k, 1.0/tau)
        parameters = 3
    elseif name=="IH_poreFormation_stressBased"
        model_func = IH_poreFormation_stressBased
        parameters = 2
    elseif name=="IH_poreFormation_strainBased"
        model_func = IH_poreFormation_strainBased_analytical_binomial
        parameters = 2
    elseif name=="IH_poreFormation_strainBased_f1"
        model_func = IH_poreFormation_strainBased_analytical_binomial
        parameters = 3
    elseif name=="IH_poreFormation_strainBased_analytical"
        model_func = IH_poreFormation_strainBased_analytical_binomial
        parameters = 2
    else
        error("Requested model '$name' is not implemented")
    end

    # setup umbridge model
    model = UMBridge.Model(
            name = name,
            inputSizes = [parameters],
            outputSizes = [1 for _ in 1:nrow(data)],
            supportsEvaluate = true
        )
    
    function evaluate_model(parameters; data::DataFrame=data)
            t_exp_all = data[:, :exposure_time]
            sigma_all = data[:, :shear_stress]
            return model_func.(t_exp_all, sigma_all, parameters...)
        end


    # evaluation function
    function evaluate(inputs, config)
        IH_values = evaluate_model(inputs[1])
        return [[value] for value in IH_values]
    end

    UMBridge.define_evaluate(model, evaluate)

    return model
end






function parse_arguments()
    s = ArgParseSettings()
    @add_arg_table s begin
        "--name"
            help = "Model name"
            arg_type = String
        "--data"
            help = "Data file path"
            arg_type = String
        "--port"
            help = "Server port"
            arg_type = Int
            default = 49152
    end
    return parse_args(s)
end

function main()
    args = parse_arguments()

    name = args["name"]
    data_file = args["data"]
    port = get(args, "port", 49152)

    println("Starting UMBridge server on port $port")
    println("Data file: $data_file")
    println("Model: $name")

    data = CSV.read(data_file, DataFrame)

    required_columns = ["exposure_time", "shear_stress"]
    if !all(col in names(data) for col in required_columns)
        error("Data file must contain columns: $(join(required_columns, ", "))")
    else 
        select!(data, required_columns)
    end
    
    # Create the model instance
    model = get_IH_model(name, data)

    println("Successfully created model: $(model.name)")

    # Serve the model
    UMBridge.serve_models([model], port)
end


if abspath(PROGRAM_FILE) == @__FILE__
    main()
end