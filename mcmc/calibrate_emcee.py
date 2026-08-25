import yaml
import numpy as np
import emcee
import pandas as pd
from scipy.stats import uniform, norm, truncnorm
from scipy.stats import t as t_dist
import umbridge
import argparse
import arviz as az
import contextlib
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import Pool

POOL_TYPES = ["serial", "thread", "process"]


class Prior:
    @staticmethod
    def _distributions_from_config(prior_config: dict):
        name = prior_config["name"]
        distribution = prior_config["distribution"]

        if distribution["type"] not in ["uniform", "normal", "truncated_normal"]:
            print(f"Distribution type {distribution["type"]} not yet supported")
            print("Aborting MCMC Calibration")
            exit(1)

        if distribution["type"] == "uniform":
            if not all(attribute in distribution["attribute"] for attribute in ("upper_bound", "lower_bound")):
                print(f"Incorrect definition of prior for parameter '{name}'",
                    f"\nA uniform prior requires `lower_bound` and `upper_bound` attributes")
                print("Aborting MCMC Calibration")
                exit(1)
            else:
                loc = distribution["attribute"]["lower_bound"]
                scale = distribution["attribute"]["upper_bound"] - distribution["attribute"]["lower_bound"]
                return uniform(loc, scale)
        elif distribution["type"] == "normal":
            if not all(attribute in distribution["attribute"] for attribute in ("loc", "scale")):
                print(f"Incorrect definition of prior for parameter '{name}'",
                    f"\nA {distribution["type"]} prior requires `loc` and `scale` attributes")
                print("Aborting MCMC Calibration")
                exit(1)
            else:
                loc = distribution["attribute"]["loc"]
                scale = distribution["attribute"]["scale"]
                return norm(loc, scale)
        elif distribution["type"] == "truncated_normal":
            if not (all(attribute in distribution["attribute"] for attribute in ("loc", "scale"))
                    and any(attribute in distribution["attribute"] for attribute in ("lower_bound", "upper_bound"))):
                print(f"Incorrect definition of prior for parameter '{name}'",
                    f"\nA {distribution["type"]} prior requires `loc`, `scale`, `lower_bound` and/or `upper_bound` attributes")
                print("Aborting MCMC Calibration")
                exit(1)
            else:
                lower_bound = distribution["attribute"].get("lower_bound", -np.inf)
                upper_bound = distribution["attribute"].get("upper_bound", np.inf)
                loc = distribution["attribute"]["loc"]
                scale = distribution["attribute"]["scale"]
                a, b = (lower_bound - loc) / scale, (upper_bound - loc) / scale
                return truncnorm(a, b, loc, scale)

    def __init__(self, config: dict, parameters: list, noise_parameters: list):
        """`noise_parameters` are the free parameters of the noise model (empty
        for the heuristic guess); they are sampled after the model parameters,
        so the two lists concatenate into the sampled parameter vector."""
        self.config = config
        self.parameters = parameters
        self.noise_parameters = noise_parameters

        all_parameters = list(parameters) + list(noise_parameters)

        prior_names = [p["name"] for p in config]
        missing = [name for name in all_parameters if name not in prior_names]
        if missing:
            print(f"No prior defined for parameter(s): {', '.join(missing)}")
            print("Aborting MCMC Calibration")
            exit(1)

        self.distributions = [
            Prior._distributions_from_config(config[prior_names.index(name)])
            for name in all_parameters
        ]

        self.all_parameters = all_parameters


class LogPrior:
    def __init__(self, prior: Prior):
        self.prior = prior

    def eval(self, parameters) -> float:
        log_p = 0.0
        for i, theta in enumerate(parameters):
            support = self.prior.distributions[i].support()
            if not (support[0] <= theta <= support[1]):
                return -np.inf
            log_p += self.prior.distributions[i].logpdf(theta)
        return log_p


class NoiseModel:
    """
    Observation-noise scale as a function of the model prediction.

    The scale of observation i is

        sigma_i = sigma + sigma_rel * IH_i ,

    with only the terms named in `parameter_names` active for a given model:

        heuristic : no free parameters -- sigma_i is the fixed `noise_sigma` guess
        uniform   : sigma            -- constant scatter, independent of IH
        linear    : sigma_rel        -- scatter proportional to IH
        affine    : sigma, sigma_rel -- a floor plus an IH-proportional part

    The free parameters are appended to the sampled parameter vector in the
    order given by `parameter_names`, so the priors in the config must be
    declared under those names.
    """

    PARAMETERS = {
        "heuristic": [],
        "uniform":   ["sigma"],
        "linear":    ["sigma_rel"],
        "affine":    ["sigma", "sigma_rel"],
    }

    def __init__(self, name: str, noise_sigma=None):
        if name not in self.PARAMETERS:
            print(f"Noise model '{name}' not supported. Choose from: {list(self.PARAMETERS)}")
            print("Aborting MCMC Calibration")
            exit(1)
        if name == "heuristic" and noise_sigma is None:
            print("The 'heuristic' noise model requires `noise_sigma` to be provided")
            print("Aborting MCMC Calibration")
            exit(1)

        self.name = name
        self.noise_sigma = noise_sigma
        self.parameter_names = list(self.PARAMETERS[name])

    @property
    def n_parameters(self) -> int:
        return len(self.parameter_names)

    @property
    def calibrated(self) -> bool:
        return self.n_parameters > 0

    def scale(self, noise_parameters, prediction_mean):
        """Per-observation noise scale, broadcast to the shape of the prediction.
        Returns None when the parameters put the scale outside its support."""
        if self.name == "heuristic":
            return np.full_like(prediction_mean, float(self.noise_sigma), dtype=float)

        if any(p <= 0.0 for p in noise_parameters):
            return None

        values = dict(zip(self.parameter_names, noise_parameters))
        sigma = np.zeros_like(prediction_mean, dtype=float)
        if "sigma" in values:
            sigma = sigma + values["sigma"]
        if "sigma_rel" in values:
            # The IH-proportional term uses the magnitude of the prediction so a
            # transient negative excursion cannot flip the scale negative.
            sigma = sigma + values["sigma_rel"] * np.abs(prediction_mean)

        if not np.all(sigma > 0.0):
            return None
        return sigma


class LogLikelihood:
    """
    Independent observation likelihood with a configurable distribution
    (`normal` or `student_t`) and a configurable noise model (see NoiseModel).

    Student's t has the same location and scale as the normal but heavier tails,
    controlled by the degrees of freedom `dof`; it downweights outlying
    measurements instead of letting them dominate the fit. dof -> inf recovers
    the normal.
    """

    DISTRIBUTIONS = ("normal", "student_t")

    def __init__(self, model, data: np.ndarray, noise_model: NoiseModel,
                 distribution_type: str = "normal", dof: float = 4.0):
        if distribution_type not in self.DISTRIBUTIONS:
            print(f"Distribution type {distribution_type} not yet supported for log_likelihood")
            print(f"Choose from: {list(self.DISTRIBUTIONS)}")
            print("Aborting MCMC Calibration")
            exit(1)
        if distribution_type == "student_t" and dof <= 0.0:
            print("Student's t likelihood requires `likelihood_dof` > 0")
            print("Aborting MCMC Calibration")
            exit(1)

        self.model = model
        self.data = data
        self.noise_model = noise_model
        self.distribution_type = distribution_type
        self.dof = dof

    def split_parameters(self, parameters):
        """Split the sampled vector into (model parameters, noise parameters)."""
        n_noise = self.noise_model.n_parameters
        if n_noise == 0:
            return list(parameters), []
        return list(parameters[:-n_noise]), list(parameters[-n_noise:])

    def predict(self, model_parameters):
        """Model prediction for one parameter set, or None if it cannot be evaluated."""
        try:
            prediction_mean = np.asarray(self.model([[*model_parameters]]))
        except Exception:
            return None

        if prediction_mean.dtype == object or not np.isfinite(prediction_mean).all():
            return None

        if prediction_mean.shape != self.data.shape:
            raise ValueError("shape of model predictions does not match observations")

        return prediction_mean

    def pointwise(self, parameters, prediction_mean=None):
        """
        Per-observation log density, flattened to one value per measurement.
        Returns None when the parameters are outside the likelihood's support --
        callers turn that into -inf. Passing an already computed
        `prediction_mean` avoids a second model evaluation.
        """
        model_parameters, noise_parameters = self.split_parameters(parameters)

        if prediction_mean is None:
            prediction_mean = self.predict(model_parameters)
        if prediction_mean is None:
            return None

        sigma = self.noise_model.scale(noise_parameters, prediction_mean)
        if sigma is None:
            return None

        if self.distribution_type == "normal":
            log_p = norm.logpdf(self.data, loc=prediction_mean, scale=sigma)
        else:
            log_p = t_dist.logpdf(self.data, self.dof, loc=prediction_mean, scale=sigma)

        return np.asarray(log_p).reshape(-1)

    def eval(self, parameters) -> float:
        log_p = self.pointwise(parameters)
        if log_p is None or not np.isfinite(log_p).all():
            return -np.inf
        return float(log_p.sum())


class LogPosterior:
    def __init__(self, log_prior: LogPrior, log_likelihood: LogLikelihood):
        self.log_prior = log_prior
        self.log_likelihood = log_likelihood

    def eval(self, parameters) -> float:
        lp = self.log_prior.eval(parameters)
        if not np.isfinite(lp):
            return lp
        return lp + self.log_likelihood.eval(parameters)


@contextlib.contextmanager
def _build_pool(pool_type: str, n_workers: int):
    if pool_type == "thread":
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            yield pool
    elif pool_type == "process":
        with Pool(processes=n_workers) as pool:
            yield pool
    else:
        yield None


def initialize_walkers(nwalkers: int, prior: Prior) -> np.ndarray:
    nparameters = len(prior.distributions)
    initial_positions = np.zeros((nwalkers, nparameters))

    for i in range(nparameters):
        initial_positions[:, i] = prior.distributions[i].rvs(size=nwalkers)

    return initial_positions

def perform_mcmc(prior, log_posterior, nwalkers=50, nburn=2500, nsteps=5000, n_workers=1, pool_type="serial"):
    if pool_type not in POOL_TYPES:
        print(f"pool_type '{pool_type}' not supported. Choose from: {POOL_TYPES}")
        exit(1)

    # Initialize Walkers
    initial_positions = initialize_walkers(nwalkers, prior)

    # Setup Sampler
    ndim = len(prior.distributions)
    with _build_pool(pool_type, n_workers) as pool:
        sampler = emcee.EnsembleSampler(nwalkers, ndim, log_posterior, pool=pool)

        # Run Calibration
        sampler.run_mcmc(initial_positions, nsteps, progress=True)

    # Extract Results (post burn-in)
    trace = sampler.chain[:, nburn:, :].reshape(-1, ndim)
    lnprob = sampler.lnprobability[:, nburn:]
    samples = sampler.chain[:, nburn:, :]

    return trace, sampler, lnprob, samples

DEFAULT_NOISE_MODEL = "uniform"
DEFAULT_LIKELIHOOD_DOF = 4.0
DEFAULT_N_PREDICTIVE = 2000


def resolve_noise_model(calibration: dict) -> NoiseModel:
    """
    Pick the noise model from the config. `noise_model` is the current key;
    configs written before it existed are honoured through the older
    `calibrate_noise` flag, which selects between the heuristic guess and a
    single constant calibrated sigma.
    """
    name = calibration.get("noise_model")
    if name is None:
        name = DEFAULT_NOISE_MODEL if calibration.get("calibrate_noise") else "heuristic"
    return NoiseModel(name, noise_sigma=calibration.get("noise_sigma"))


def build_predictive_idata(sampler, prior, log_likelihood, nburn, observed,
                           n_predictive=DEFAULT_N_PREDICTIVE):
    """
    Evaluate the model on a thinned subset of the post burn-in chain and collect
    the per-observation log likelihood and the posterior predictive.

    The pointwise log likelihood is what LOO/WAIC need, and it is not recoverable
    from the posterior alone once the model server is gone -- so it is computed
    here, while the server is still up. Thinning keeps the cost at
    `n_predictive` model evaluations and the file at a few MB, instead of
    carrying a (chain x draw x observation) array for the whole chain.
    """
    chain = sampler.chain[:, nburn:, :]
    n_chains, n_draws, _ = chain.shape
    if n_draws == 0:
        print("No post burn-in draws left; skipping predictive inference data")
        return None

    per_chain = max(1, int(np.ceil(n_predictive / n_chains)))
    stride = max(1, n_draws // per_chain)
    thinned = chain[:, ::stride, :][:, :per_chain, :]
    n_kept = thinned.shape[1]

    n_obs = observed.size
    log_lik = np.empty((n_chains, n_kept, n_obs))
    predictive = np.empty((n_chains, n_kept, n_obs))

    print(f"Evaluating {n_chains * n_kept} thinned draws for the predictive inference data")
    for c in range(n_chains):
        for d in range(n_kept):
            parameters = thinned[c, d, :]
            model_parameters, _ = log_likelihood.split_parameters(parameters)
            prediction = log_likelihood.predict(model_parameters)
            pointwise = (None if prediction is None
                         else log_likelihood.pointwise(parameters, prediction_mean=prediction))
            predictive[c, d, :] = (np.nan if prediction is None
                                   else np.asarray(prediction).reshape(-1))
            log_lik[c, d, :] = -np.inf if pointwise is None else pointwise

    posterior = {name: thinned[:, :, i] for i, name in enumerate(prior.all_parameters)}
    data_label = "fHb"
    groups = {
        "posterior": posterior,
        "log_likelihood": {data_label: log_lik},
        "posterior_predictive": {data_label: predictive},
        "observed_data": {data_label: observed.reshape(-1)},
    }
    try:
        # arviz >= 1.0 takes the groups as one nested mapping ...
        return az.from_dict(groups)
    except TypeError:
        # ... arviz 0.x took them as keyword arguments.
        return az.from_dict(**groups)


def parse_arguments():
    parser = argparse.ArgumentParser(description='MCMC Calibration with `emcee`')
    parser.add_argument('--config', type=str,
                        help='YAML file for Configuration Parameters')
    parser.add_argument('--data', type=str,
                        help='Path to Data File')
    parser.add_argument('--port', type=int, default=49152,
                       help='Server port')
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_arguments()
    config_file = args.config
    data_file = args.data
    port = args.port

    with open(config_file) as f:
        config = yaml.safe_load(f)

    calibration = config["calibration"]

    # Load Data 
    required_columns = calibration["data"]
    df = pd.read_csv(
        data_file,
        usecols = required_columns
        )
    data = df[required_columns].to_numpy()

    # Connect Model
    try:
        model_name = config["model"]["name"]
        model = umbridge.HTTPModel(f"http://localhost:{args.port}", model_name)
        print(f"Connected to model: {model_name}")
    except Exception as e:
        print(f"Error connecting to model: {e}")
        exit(1)

    # Noise model decides which noise parameters are sampled alongside the
    # model parameters, so it has to be resolved before the priors.
    noise_model = resolve_noise_model(calibration)
    print(f"Noise model: {noise_model.name} "
          f"(free parameters: {noise_model.parameter_names or 'none'})")

    # Define Prior Distributions
    prior = Prior(calibration["priors"],
                    parameters=calibration["parameters"],
                    noise_parameters=noise_model.parameter_names)

    likelihood_type = calibration.get("likelihood", "normal")
    likelihood_dof = float(calibration.get("likelihood_dof", DEFAULT_LIKELIHOOD_DOF))
    print(f"Likelihood: {likelihood_type}"
          + (f" (dof = {likelihood_dof:g})" if likelihood_type == "student_t" else ""))

    log_prior = LogPrior(prior)
    log_likelihood = LogLikelihood(model, data,
                                    noise_model=noise_model,
                                    distribution_type=likelihood_type,
                                    dof=likelihood_dof)
    log_posterior = LogPosterior(log_prior, log_likelihood)

    # Perform MCMC Calibration
    nburn = calibration["nburn"]
    trace, sampler, _, _ = perform_mcmc(prior, log_posterior.eval,
                nwalkers=calibration["nwalkers"],
                nburn=nburn,
                nsteps=calibration["nsteps"],
                n_workers=calibration.get("n_workers", 1),
                pool_type=calibration.get("pool_type", "serial"))

    print(f"MCMC completed. Trace shape: {trace.shape}")

    # Idata for Diagnostics with Arviz
    idata = az.from_emcee(sampler, var_names = prior.all_parameters)
    idata.to_netcdf(f"mcmc_idata.nc")
    print(f"Calibration inference data saved to mcmc_idata.nc")

    # Pointwise log likelihood and posterior predictive, for cross-experiment
    # comparison (LOO/WAIC, predictive checks). Written as a separate file so
    # the diagnostics unit keeps reading the full, untouched chain.
    predictive_idata = build_predictive_idata(
        sampler, prior, log_likelihood, nburn, data,
        n_predictive=int(calibration.get("n_predictive", DEFAULT_N_PREDICTIVE)),
    )
    if predictive_idata is not None:
        predictive_idata.to_netcdf("predictive_idata.nc")
        print("Predictive inference data saved to predictive_idata.nc")
