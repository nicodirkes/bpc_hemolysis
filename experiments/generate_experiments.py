#!/usr/bin/env python3
"""
Generate experiment parameter files from experiments.yml.

Produces one experiment_<hash>.yml per combination of sweep dimensions
(species x models x prior_configuration x calibrate_noise x use_julia),
in the same format as the single-run params files.
"""

import yaml
import hashlib
import itertools
import sys
from pathlib import Path
from typing import Any, Dict, List


def generate_hash(species: str, model_name: str, prior_config_name: str,
                  calibrate_noise: bool) -> str:
    key = f"species={species}|model={model_name}|prior_config={prior_config_name}|calibrate_noise={calibrate_noise}"
    return hashlib.sha256(key.encode()).hexdigest()[:8]


def build_priors(parameters: List[str], noise_parameters: List[str],
                 calibrate_noise: bool, prior_config_name: str,
                 prior_configurations: Dict, prior_library: Dict) -> List[Dict]:
    prior_config = prior_configurations[prior_config_name]
    params_to_include = list(parameters)
    if calibrate_noise:
        params_to_include += list(noise_parameters)

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


def build_experiment(species: str, model_name: str, prior_config_name: str,
                     calibrate_noise: bool,
                     config: Dict) -> Dict:
    model_def = config['model_definitions'][model_name]
    cal = config['calibration']
    model_server = config.get('model_server', {})
    parameters = model_def['parameters']
    noise_parameters = cal['noise_parameters']

    priors = build_priors(
        parameters, noise_parameters, calibrate_noise,
        prior_config_name, config['prior_configurations'], config['prior_library']
    )

    return {
        'species': species,
        'model': {
            'name': model_name,
            'control_variables': list(model_def['control_variables']),
            'use_julia': model_def.get('use_julia', False),
            'n_workers': model_server.get('n_workers', 1),
        },
        'calibration': {
            'nwalkers': cal['nwalkers'],
            'nburn': cal['nburn'],
            'nsteps': cal['nsteps'],
            'n_workers': cal.get('n_workers', 1),
            'pool_type': cal.get('pool_type', 'serial'),
            'parameters': list(parameters),
            'noise_parameters': list(noise_parameters),
            'calibrate_noise': calibrate_noise,
            'noise_sigma': cal['noise_sigma'],
            'data': list(cal['data']),
            'likelihood': cal['likelihood'],
            'priors': priors,
        }
    }


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

    sweep = config['sweep']
    dim_values = [
        sweep['species'],
        sweep['models'],
        sweep['prior_configuration'],
        sweep['calibrate_noise'],
    ]

    if output_dir != Path("."):
        output_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for species, model_name, prior_config_name, calibrate_noise in itertools.product(*dim_values):
        params = build_experiment(species, model_name, prior_config_name, calibrate_noise, config)
        hash_val = generate_hash(species, model_name, prior_config_name, calibrate_noise)
        params['experiment_hash'] = hash_val

        output_file = output_dir / f"experiment_{hash_val}.yml"
        with open(output_file, 'w') as f:
            yaml.dump(params, f, default_flow_style=False, sort_keys=False)

        print(f"Created {output_file}", file=sys.stderr)
        count += 1

    print(f"Generated {count} experiment files in {output_dir}", file=sys.stderr)


if __name__ == '__main__':
    main()
