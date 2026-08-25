#!/usr/bin/env python3
"""
Generate experiment parameter files from experiments.yml.

Produces one experiment_<hash>.yml per combination of the sweep dimensions, in
the same format as the single-run params files. The sweep dimensions are read
from the `sweep` block, so adding a dimension there is enough to widen the
study -- each dimension name must appear in SWEEP_DIMENSIONS below, which fixes
the order the combinations are enumerated (and hashed) in.
"""

import yaml
import hashlib
import itertools
import sys
from pathlib import Path
from typing import Any, Dict, List

# Sweep dimensions in enumeration order, mapped to the sweep-block key that
# lists their levels. Order is part of the experiment hash, so appending new
# dimensions at the end keeps existing hashes (and therefore resumed runs) stable.
SWEEP_DIMENSIONS = [
    ("species",            "species"),
    ("model",              "models"),
    ("prior_configuration", "prior_configuration"),
    ("noise_model",        "noise_model"),
    ("likelihood",         "likelihood"),
    ("data_mode",          "data_mode"),
]

# Free parameters of each noise model, mirroring NoiseModel.PARAMETERS in
# mcmc/calibrate_emcee.py: sigma_i = sigma + sigma_rel * IH_i, with only the
# listed terms active. The heuristic model samples nothing and uses the fixed
# `noise_sigma` guess instead.
NOISE_PARAMETERS = {
    "heuristic": [],
    "uniform":   ["sigma"],
    "linear":    ["sigma_rel"],
    "affine":    ["sigma", "sigma_rel"],
}

# Levels assumed when a sweep block leaves a dimension out, so that a config
# written against the earlier four-dimension sweep still generates the same runs.
DIMENSION_DEFAULTS = {
    "noise_model":  ["uniform"],
    "likelihood":   ["normal"],
    "data_mode":    ["raw"],
}


def generate_hash(combination: Dict[str, Any]) -> str:
    key = "|".join(f"{name}={combination[name]}" for name, _ in SWEEP_DIMENSIONS)
    return hashlib.sha256(key.encode()).hexdigest()[:8]


def build_priors(parameters: List[str], noise_parameters: List[str],
                 prior_config_name: str,
                 prior_configurations: Dict, prior_library: Dict) -> List[Dict]:
    prior_config = prior_configurations[prior_config_name]
    params_to_include = list(parameters) + list(noise_parameters)

    priors = []
    for param_name in params_to_include:
        if param_name not in prior_config:
            print(f"Error: parameter '{param_name}' not found in prior configuration '{prior_config_name}'", file=sys.stderr)
            sys.exit(1)
        prior_type = prior_config[param_name]
        if param_name not in prior_library:
            print(f"Error: no prior library entry for parameter '{param_name}'", file=sys.stderr)
            sys.exit(1)
        if prior_type not in prior_library[param_name]:
            print(f"Error: distribution type '{prior_type}' not defined for parameter '{param_name}' in prior_library", file=sys.stderr)
            sys.exit(1)
        priors.append({
            'name': param_name,
            'distribution': {
                'type': prior_type,
                'attribute': dict(prior_library[param_name][prior_type]),
            }
        })
    return priors


def build_experiment(combination: Dict[str, Any], config: Dict) -> Dict:
    model_name = combination["model"]
    noise_model = combination["noise_model"]

    model_def = config['model_definitions'][model_name]
    cal = config['calibration']
    model_server = config.get('model_server', {})
    parameters = model_def['parameters']

    if noise_model not in NOISE_PARAMETERS:
        print(f"Error: unknown noise model '{noise_model}'. "
              f"Choose from: {list(NOISE_PARAMETERS)}", file=sys.stderr)
        sys.exit(1)
    noise_parameters = NOISE_PARAMETERS[noise_model]

    priors = build_priors(
        parameters, noise_parameters, combination["prior_configuration"],
        config['prior_configurations'], config['prior_library']
    )

    return {
        'species': combination["species"],
        'model': {
            'name': model_name,
            'control_variables': list(model_def['control_variables']),
            'use_julia': model_def.get('use_julia', False),
            'n_workers': model_server.get('n_workers', 1),
        },
        'dataset': {
            # raw keeps every repetition as its own observation; averaged
            # collapses the repetitions of each control-variable set to their mean.
            'mode': combination["data_mode"],
        },
        'calibration': {
            'nwalkers': cal['nwalkers'],
            'nburn': cal['nburn'],
            'nsteps': cal['nsteps'],
            'n_workers': cal.get('n_workers', 1),
            'pool_type': cal.get('pool_type', 'serial'),
            'parameters': list(parameters),
            'noise_model': noise_model,
            'noise_parameters': list(noise_parameters),
            # Retained for readers that predate `noise_model` (e.g. the report's
            # run-configuration table): true whenever the noise is inferred
            # rather than guessed.
            'calibrate_noise': bool(noise_parameters),
            'noise_sigma': cal['noise_sigma'],
            'data': list(cal['data']),
            'likelihood': combination["likelihood"],
            'likelihood_dof': cal.get('likelihood_dof', 4.0),
            'n_predictive': cal.get('n_predictive', 2000),
            'priors': priors,
        }
    }


def is_compatible(combination: Dict[str, Any], config: Dict) -> bool:
    """
    Whether a combination is worth running at all.

    A model may declare `incompatible_noise_models`. The pore formation models
    predict exactly zero below the onset of pore opening, and a purely
    IH-proportional noise scale is zero there, so every draw is rejected: with a
    fixed relaxation time nothing is samplable at all, and with a free one the
    prior is silently truncated to the region with no zero predictions. Skipping
    those combinations keeps failed and misleading runs out of the sweep.
    """
    model_def = config['model_definitions'][combination["model"]]
    return combination["noise_model"] not in model_def.get('incompatible_noise_models', [])


def sweep_levels(sweep: Dict) -> Dict[str, List]:
    levels = {}
    for name, sweep_key in SWEEP_DIMENSIONS:
        if sweep_key in sweep:
            levels[name] = list(sweep[sweep_key])
        elif name in DIMENSION_DEFAULTS:
            levels[name] = list(DIMENSION_DEFAULTS[name])
        else:
            print(f"Error: sweep dimension '{sweep_key}' is missing from the sweep block",
                  file=sys.stderr)
            sys.exit(1)
    return levels


def main():
    if len(sys.argv) < 2:
        print("Usage: generate_experiments.py <experiments.yml> [output_dir]")
        sys.exit(1)

    experiments_file = Path(sys.argv[1])
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".")

    if not experiments_file.exists():
        print(f"Error: {experiments_file} not found", file=sys.stderr)
        sys.exit(1)

    with open(experiments_file) as f:
        config = yaml.safe_load(f)

    levels = sweep_levels(config['sweep'])
    names = [name for name, _ in SWEEP_DIMENSIONS]

    if output_dir != Path("."):
        output_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    skipped = 0
    for values in itertools.product(*(levels[name] for name in names)):
        combination = dict(zip(names, values))
        if not is_compatible(combination, config):
            print(f"Skipping incompatible combination: "
                  f"{', '.join(f'{k}={v}' for k, v in combination.items())}", file=sys.stderr)
            skipped += 1
            continue
        params = build_experiment(combination, config)
        hash_val = generate_hash(combination)
        params['experiment_hash'] = hash_val

        output_file = output_dir / f"experiment_{hash_val}.yml"
        with open(output_file, 'w') as f:
            yaml.dump(params, f, default_flow_style=False, sort_keys=False)

        print(f"Created {output_file}  ({', '.join(f'{k}={v}' for k, v in combination.items())})",
              file=sys.stderr)
        count += 1

    print(f"Generated {count} experiment files in {output_dir}"
          + (f" ({skipped} incompatible combinations skipped)" if skipped else ""), file=sys.stderr)


if __name__ == '__main__':
    main()
