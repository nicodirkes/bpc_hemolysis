script_description = '''
Script for preprocessing tabular data from experiments
Author: MK, AC
Inputs: Tabular data with three columns (shear_stress, exposure_time, fHb)
Output: Tabular data with: 
            - multiple fHb measurements grouped by shear_stress and exposure_time
            - additionally computed columns for mean and standard deviation of fHb measurements
'''

import pandas as pd
import argparse
import os

parser = argparse.ArgumentParser(description=script_description)
parser.add_argument("--indir")
parser.add_argument("--outdir")
parser.add_argument("--prefix")
parser.add_argument("species")

args = parser.parse_args()
input_directory = str(args.indir or ".")
output_directory = str(args.outdir or ".")
prefix = str(args.prefix or '')
species = args.species
input_filename = os.path.join(f"{input_directory}",f"{prefix + species}.csv")
output_filename = os.path.join(f"{output_directory}",f"{prefix + species}_processed.csv")
required_columns = ['shear_stress', 'exposure_time', 'fHb']

print(f"Processing {input_filename}")

## Step 1: Read Data
df = pd.read_csv(
    input_filename,
    usecols = required_columns
    )

## Step 2: Any Preprocessing goes here

## Step 3: Write preprocessed data
if not os.path.isdir(output_directory):
    os.mkdir(output_directory)
df.to_csv(output_filename, index=False)

print(f"Finished {output_filename}")
