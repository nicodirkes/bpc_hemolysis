import numpy as np
import math
from scipy.integrate import quad
import csv

# define logarithmic function and inverse
logF = np.log
invLogF = np.exp

# Polynomial coefficients for the area strain to pore area conversion (fifth order polynomial fit)
p = [-0.1593, 0.6332, 32.3921, -48.9149, 37.3125, -13.4134]
G1 = 3750
G2 = 42000

def computeEffShearStrainBased(t, f1):
    return 1 - np.exp(-f1 * t)

def computePoreAreaInterpolated(G):
    if G < G1:
        return 0.0
    elif G > G2:
        return np.ones_like(G) * sum(p)
    else:
        return np.polyval(p[::-1], G/G2)
    
def IH_poreFormation_stressBased(t_exp, sigma_exp, h, k, log=False, mu=0.0035):
    """
    Model #4: Compute IH with pore formation model based on stress-based morphology.
    """
    G_exp = sigma_exp / mu  # shear rate

    Apt = computePoreAreaInterpolated(G_exp) * t_exp
    if log:
        Apt = max(Apt, 1e-10)  # ensure Apt is not zero for log calculation
        return -h + k * logF(sigma_exp) + logF(Apt) + logF(100)
    else:
        return invLogF(-h) * (sigma_exp ** k) * Apt * 100

def IH_poreFormation_strainBased(t_exp, sigma_exp, h, k, log=False, mu=0.0035, f1=5.0, analytical=False):
    """
    Model #3: Compute IH with pore formation model based on strain-based morphology.
    Sensible limits:
    0 <= h <= 20
    0 <= k <= 2
    """
    G_exp = sigma_exp / mu  # shear rate

    # Compute integral of pore area formation
    if analytical:
        Apt = integral_poreFormation_analytical(t_exp, G_exp, f1)
    else:
        Ap = lambda t: computePoreAreaInterpolated(G_exp * computeEffShearStrainBased(t, f1))
        Apt, _ = quad(Ap, 0, t_exp)

    if log:
        Apt = max(Apt, 1e-10)  # ensure Apt is not zero for log calculation
        return -h + k * logF(sigma_exp) + logF(Apt) + logF(100)
    else:
        return invLogF(-h) * (sigma_exp ** k) * Apt * 100

def integral_poreFormation_analytical(t_exp, G_exp, f=5.0):
    """
    Model #3: Compute IH with pore formation model based on strain-based morphology.
    Use analytical integration formula.
    """
    G = G_exp  # shear rate

    # Analytical integral of pore area formation
    
    # First: find transition time points where G_eff crosses interpolation limits
    t1 = -np.log(1 - G1 / G) / f if G > G1 else t_exp
    t1 = min(t1, t_exp)
    t2 = -np.log(1 - G2 / G) / f if G > G2 else t_exp
    t2 = min(t2, t_exp)

    # Integrate in three parts
    # Part 1: from 0 to t1
    integral = 0.0  # pore area is zero in this range
    # Part 2: from t1 to t2 (if applicable)
    if t2 > t1:
        for i in range(6):  # iterate over polynomial terms
            integral += p[i] * (G/G2)**i * integrate_normalized_Geff(f, i, t1, t2)

    # Part 3: from t2 to t_exp (if applicable)
    if t_exp > t2:
        integral += sum(p) * (t_exp - t2)

    return integral

def integrate_normalized_Geff(f, i, t0, t1):
    """
    Helper function to integrate (1 - exp(-f*t))^i from t0 to t1.
    """
    # if i is an integer, we can use the binomial expansion
    if isinstance(i, int):
        integral = 0.0
        for k in range(1, i+1):
            binom = math.comb(i, k)
            integral += binom * (-1)**(k+1) / k * (np.exp(-k*f*t1) - np.exp(-k*f*t0))
        integral = integral / f + (t1 - t0)
    else:
        from scipy.special import hyp2f1 # use hypergeometric function for non-integer i
        antiderivative = lambda t: (1 - np.exp(-f*t))**(i+1) * hyp2f1(1, i+1, i+2, 1 - np.exp(-f*t)) / (f * (i+1))
        integral = antiderivative(t1) - antiderivative(t0)
    return integral

def IH_powerLaw_strainBased(t_exp, sigma_exp, A, alpha, beta, f1=5.0, log=False, analytical=False):
    """
        Model #2: Strain-based power law.
        Sensible limits for the parameters:
        0 <= A <= 20
        0.5 <= alpha <= 3
        0.01 <= beta <= 1
    """
    if analytical:
        G_int = integrate_normalized_Geff(f1, alpha/beta, 0, t_exp)
    else:
        Geff_normalized = lambda t: computeEffShearStrainBased(t, f1)
        G_int, _ = quad(lambda t: Geff_normalized(t) ** (alpha / beta), 0, t_exp)

    if log:
        return -A + alpha * logF(sigma_exp) + beta * logF(G_int) + logF(100)
    else:
        return invLogF(-A) * sigma_exp**alpha * G_int ** beta * 100

def IH_powerLaw_stressBased(t_exp, sigma_exp, A, alpha, beta, log=False):
    """
        Model #1: Stress-based power law.
        Sensible limits for the parameters:
        0 <= A <= 20
        0.5 <= alpha <= 2.5
        0.01 <= beta <= 1
    """
    if log:
        return -A + alpha * logF(sigma_exp) + beta * logF(t_exp) + logF(100)
    else:
        return invLogF(-A) * (sigma_exp ** alpha) * (t_exp ** beta) * 100  # convert to percentage


def get_input_data(fname):
    """
    Load input data from a CSV file.
    The CSV file should contain columns for 'exposure_time' and 'shear_stress'.
    Returns a 2D numpy array with columns [exposure_time, shear_stress].
    """
    data = csv.reader(open(fname, 'r'))
    header = next(data)
    data = np.array(list(data), dtype=float)

    # get data by header
    t_exp = data[:, header.index('exposure_time')]
    sigma_exp = data[:, header.index('shear_stress')]

    return np.array([t_exp, sigma_exp]).T

def get_IH_model(model_name, mu, f1, log, analytical):
    """
    Returns the appropriate IH model function based on the model name.
    """
    if model_name == 'IH_powerLaw_stressBased':
        def computeIH_powerLaw_stressBased(x, p):
            assert len(p) == 3, "Parameters should contain exactly three values: [A, alpha, beta]"
            assert len(x) == 2, "Input x should contain exactly rows: [t_exp, sigma]"
            return IH_powerLaw_stressBased(*x, *p, log)
        return computeIH_powerLaw_stressBased
    elif model_name == 'IH_powerLaw_strainBased':
        def computeIH_powerLaw_strainBased(x, p):
            assert len(p) == 3, "Parameters should contain exactly three values: [A, alpha, beta]"
            assert len(x) == 2, "Input x should contain exactly rows: [t_exp, sigma]"
            return IH_powerLaw_strainBased(*x, *p, f1, log=log, analytical=analytical)
        return computeIH_powerLaw_strainBased
    elif model_name == 'IH_poreFormation_strainBased':
        def computeIH_poreFormation(x, p):
            assert len(p) == 2, "Parameters should contain exactly two values: [h, k]"
            assert len(x) == 2, "Input x should contain exactly rows: [t_exp, sigma]"
            return IH_poreFormation_strainBased(*x, *p, log=log, mu=mu, f1=f1, analytical=analytical)
        return computeIH_poreFormation
    elif model_name == 'IH_poreFormation_stressBased':
        def computeIH_poreFormation_stressBased(x, p):
            assert len(p) == 2, "Parameters should contain exactly two values: [h, k]"
            assert len(x) == 2, "Input x should contain exactly rows: [t_exp, sigma]"
            return IH_poreFormation_stressBased(*x, *p, log=log, mu=mu)
        return computeIH_poreFormation_stressBased
    else:
        raise ValueError(f"Unknown model name: {model_name}")

def evaluate_model(parameters, fname_controlVars='data.csv', model_name='IH_powerLaw_strainBased', log=False,
                   mu=0.0035, f1=5.0, analytical=True):
    """
    Computes IH using the specified model with given parameters.
    Inputs:
    - parameters: list of model parameters [A, alpha, beta]
    - fname_controlVars: path to the CSV file containing control variables
    - model_name: name of the model to use ('IH_powerLaw_strainBased', 'IH_powerLaw_stressBased', 'IH_poreFormation')
    - mu: viscosity (default 0.0035), only used for pore formation model
    - f1: parameter for pore formation model and strain-based power law (default 5.0)
    Returns:
    - log (bool): whether to use logarithmic scaling, leading to log(IH) output
    - A list of computed IH values for each control variable point.
    """

    IH_model = get_IH_model(model_name, mu, f1, log, analytical)
    input_data = get_input_data(fname_controlVars)

    return [ IH_model(x, parameters) for x in input_data ]

def main():
    """Example usage of the IH power-law models."""

    # example parameters for the power-law model
    parameters = [1.228e-7, 1.9918, 0.6606]

    # example parameters for the pore formation model
    parameters_pore = [1e-4, 0.8]
    
    fname_data = 'data.csv'
    output_data_stressBased = evaluate_model(parameters, fname_controlVars=fname_data, model_name='IH_powerLaw_stressBased')
    output_data_strainBased = evaluate_model(parameters, fname_controlVars=fname_data, model_name='IH_powerLaw_strainBased', f1=5.0)
    output_data_pore_strain = evaluate_model(parameters_pore, fname_controlVars=fname_data, model_name='IH_poreFormation_strainBased', mu=0.00424, f1=5.0)
    output_data_pore_stress = evaluate_model(parameters_pore, fname_controlVars=fname_data, model_name='IH_poreFormation_stressBased', mu=0.00424, f1=5.0)

    print("Output data (stress-based):", output_data_stressBased)
    print("Output data (strain-based):", output_data_strainBased)
    print("Output data (pore formation, strain-based):", output_data_pore_strain)
    print("Output data (pore formation, stress-based):", output_data_pore_stress)


if __name__ == "__main__":
    main()