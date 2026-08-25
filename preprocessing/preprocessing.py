script_description = '''
Script for preprocessing tabular data from experiments
Author: MK, AC
Inputs: Tabular data with three columns (shear_stress, exposure_time, fHb)
Output: Tabular data with:
            - `--mode raw`: every measurement kept as its own row, i.e. the
              repetitions per set of control variables stay separate
            - `--mode averaged`: one row per set of control variables, with fHb
              replaced by the mean over its repetitions, plus the repetition
              count and the sample standard deviation of that group
'''

import pandas as pd
import argparse
import os

MODES = ("raw", "averaged")

parser = argparse.ArgumentParser(description=script_description)
parser.add_argument("--indir")
parser.add_argument("--outdir")
parser.add_argument("--prefix")
parser.add_argument("--mode", choices=MODES, default="raw",
                    help="raw: keep every repetition as a separate observation. "
                         "averaged: collapse repetitions to the group mean.")
parser.add_argument("species")

args = parser.parse_args()
input_directory = str(args.indir or ".")
output_directory = str(args.outdir or ".")
prefix = str(args.prefix or '')
species = args.species
mode = args.mode
input_filename = os.path.join(f"{input_directory}",f"{prefix + species}.csv")
output_filename = os.path.join(f"{output_directory}",f"{prefix + species}_processed.csv")
required_columns = ['shear_stress', 'exposure_time', 'fHb']
control_variables = ['shear_stress', 'exposure_time']

print(f"Processing {input_filename} (mode: {mode})")

## Step 1: Read Data
df = pd.read_csv(
    input_filename,
    usecols = required_columns
    )

## Step 2: Collapse repetitions when the averaged mode is requested.
#  Raw keeps one row per measurement, so a set of control variables with n
#  repetitions contributes n observations to the likelihood. Averaged keeps one
#  row per set of control variables; n_repetitions and fHb_std travel with it so
#  downstream units can weight or inspect the collapsed groups.
if mode == "averaged":
    grouped = df.groupby(control_variables, as_index=False, sort=False).agg(
        fHb=('fHb', 'mean'),
        fHb_std=('fHb', 'std'),
        n_repetitions=('fHb', 'size'),
    )
    # A group with a single measurement has no sample standard deviation; 0.0
    # keeps the column numeric rather than propagating NaN into later units.
    grouped['fHb_std'] = grouped['fHb_std'].fillna(0.0)
    df = grouped[control_variables + ['fHb', 'fHb_std', 'n_repetitions']]
    print(f"Collapsed {grouped['n_repetitions'].sum()} measurements into {len(df)} control-variable groups")

## Step 3: Write preprocessed data
if not os.path.isdir(output_directory):
    os.mkdir(output_directory)
df.to_csv(output_filename, index=False)

print(f"Finished {output_filename} ({len(df)} rows)")
