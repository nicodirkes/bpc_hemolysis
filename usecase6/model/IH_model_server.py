import umbridge
import numpy as np
import pandas as pd
import os
import argparse
from src.IH_model import IH_powerLaw_stressBased, IH_powerLaw_strainBased, IH_poreFormation_stressBased, IH_poreFormation_strainBased
class IH_Model(umbridge.Model):
    
    _data = None  # Class variable to store shared data
    
    def __init__(self, name):
        self.name = name
        if name == "IH_powerLaw_stressBased":
            self.params = 3
            self.model_func = np.vectorize(IH_powerLaw_stressBased)
        elif name == "IH_powerLaw_strainBased":
            self.params = 3
            self.model_func = np.vectorize(IH_powerLaw_strainBased)
        elif name == "IH_poreFormation_stressBased":
            self.params = 2
            self.model_func = np.vectorize(IH_poreFormation_stressBased)
        elif name == "IH_poreFormation_strainBased":
            self.params = 2
            self.model_func = np.vectorize(IH_poreFormation_strainBased)
        elif name == "IH_poreFormation_strainBased_analytical":
            self.params = 2
            self.model_func = np.vectorize(
                lambda t, s, h, k: IH_poreFormation_strainBased(t, s, h, k, analytical=True))
        else:
            print("Requested Model is Not Implemented")
            exit(1)

    @classmethod
    def load_data(cls, data_file):
        """Load data once and share across all model instances."""
        if cls._data is None:
            required_columns = ['exposure_time', 'shear_stress']
            df = pd.read_csv(
                data_file,
                usecols = required_columns
                )

            cls._data = df[required_columns].to_numpy()
            print(f"Loaded {data_file} with {len(cls._data)} rows")
        return cls._data

    def get_input_sizes(self, config):
        return [self.params]

    def get_output_sizes(self, config):
        return [1]*len(self._data)

    def __call__(self, parameters, config):

        try:
            # Parameter validation
            if len(parameters[0]) != self.params:
                raise ValueError(f"Model expects {self.params} parameters, got {len(parameters[0])}")
            IH_values = self.evaluate_model(parameters[0])
            return IH_values.tolist()
        except Exception as e:
            print(f"Error in model: {e}")
            raise e

    def supports_evaluate(self):
        return True

    def evaluate_model(self, parameters):
        """Evaluate the model with given parameters."""
        t_exp_all = self._data[:, 0]
        sigma_all = self._data[:, 1]

        IH_all = self.model_func(t_exp_all, sigma_all, *parameters)
        return IH_all.reshape(-1, 1)

def parse_arguments():
    parser = argparse.ArgumentParser(description='IH Model UMBridge Server')
    parser.add_argument('--name', type=str, 
                       help='Model name')
    parser.add_argument('--data', type=str, 
                       help='Data file path')
    parser.add_argument('--port', type=int, default=49152,
                       help='Server port')
    parser.add_argument('--n_workers', type=int, default=1,
                       help='Number of worker threads for the UMBridge server')
    return parser.parse_args()

def main():
    args = parse_arguments()
    name = args.name
    data_file = args.data
    port = args.port
    max_workers = args.n_workers

    print(f"Starting UMBridge server on port {port}")
    print(f"Data file: {data_file}")
    print(f"Model: {name}")
    
    # Load shared data once
    IH_Model.load_data(data_file)
    
    # Create the model instance
    model = IH_Model(name)
    print(f"Successfully created model: {model.name}")
    
    # Serve the model
    umbridge.serve_models([model], port, max_workers=max_workers)

if __name__ == "__main__":
    main()