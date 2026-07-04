# Bayesian Parameter Calibration in Blood Hemolysis Modeling

This computational study calibrates the parameters of a computational
hemolysis model against experimental data. Hemolysis models predict the fraction
of red blood cells damaged when blood is subjected to mechanical load, and are
used to assess blood-handling medical devices such as ventricular assist devices.
Such models expose empirical coefficients that must be identified from
experiments before the model can be applied predictively.

Here the coefficients are inferred within a Bayesian framework: rather than a
single best fit, the calibration returns posterior distributions over the
parameters, so that experimental scatter and model uncertainty are carried
through into the estimates. Inference is performed with Markov Chain Monte Carlo,
and the same setup can be applied to individual datasets or swept across blood
sources and competing model formulations.

This computational study was built with the
[SHOWME.how](https://mbd-rwth.github.io/showmehow/) approach.

<p align="left">
  <img src="assets/showmehow_logo.svg" alt="SHOWME.how" height="64">
  &nbsp;&nbsp;&nbsp;
  <img src="assets/logo_mbd_rgb.png" alt="MBD – RWTH Aachen University" height="64">
</p>

## Components of the study

### Computational units

- **Forward model** predicts a hemolysis index from the flow conditions
  (control variables) and the model parameters. It is implemented in both
  **Python** and **Julia**, selectable at runtime via `model.use_julia`.
- **MCMC calibration** infers the posterior over the parameters with the
  affine-invariant ensemble sampler (Goodman & Weare) as implemented in
  [`emcee`](https://emcee.readthedocs.io/), using a Gaussian likelihood, an
  optionally calibrated noise term, and configurable priors. Inference results
  are exported as NetCDF via [ArviZ](https://python.arviz.org/).
- **Report** compiles the calibration results (including the sampler traces) into
  a generated report; **diagnostics** compute convergence statistics.

### Data

- **Blood hemolysis measurements** for different species (human, bovine, ovine,
  porcine), fetched from a remote data repository and preprocessed into a common
  CSV format.
- **Deterministic calibration data** (`deterministic_calibration/`): reference
  coefficient sets from the literature, in JSON.

### Human collaborators

- **Nico Dirkes** | CATS, RWTH Aachen | blood hemolysis modeling specialist
- **V. Mithlesh Kumar** | MBD, RWTH Aachen | uncertainty quantification
- **Alan Correa** | MBD, RWTH Aachen | research software engineering

## Installation

1. **Conda / Mamba / Micromamba**: a package manager for the unit environments
   ([Conda](https://docs.conda.io/projects/conda/en/latest/user-guide/install/index.html) /
   [Mamba](https://github.com/conda-forge/miniforge#install) /
   [Micromamba](https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html#automatic-install)).
2. Create and activate the project environment (this also installs Nextflow):
   ```
   conda env create -f environment.yml
   conda activate showmehow
   ```
3. A container runtime for the **Julia** forward model:
   [Docker](https://docs.docker.com/get-docker/) locally, or
   [Apptainer](https://apptainer.org/docs/admin/latest/installation.html#installing-apptainer)
   on HPC.

## Usage

1. **Single calibration** runs one configuration:
   ```
   nextflow run main.nf --config_file params.yml
   ```
   `params.yml` sets the `species`, the model, whether to use the
   Julia forward model (`model.use_julia`), and the calibration settings and
   priors. Ready-made configs for each model variant are provided as `params-*.yml`.

2. **Orchestrated experiments** run a sweep over many configurations. Define the
   combinations in `experiments.yml`, then:
   ```
   nextflow run experiments.nf --config_file experiments.yml
   ```
   Every combination of the `sweep` dimensions (species, model, prior
   configuration, ...) produces one calibration, sharing the common calibration
   and model-server settings. Nextflow limits concurrency to the available
   resources and skips runs that have already completed on a rerun (`-resume`).

   Available options:
   - **Species:** `human`, `bovine`, `ovine`, `porcine`
   - **Models:** `IH_powerLaw_stressBased`, `IH_powerLaw_strainBased`,
     `IH_poreFormation_stressBased`, `IH_poreFormation_strainBased`

   More options for the orchestrated version are on the way.

3. **Execution profiles** select the container engine with `-profile`:
   - `-profile local` (**default** if omitted): Docker, for a local workstation.
   - `-profile cluster`: Apptainer, for a shared cluster node. Process execution
     still uses the local executor (no batch scheduler yet).

   ```
   nextflow run main.nf --config_file params.yml -profile cluster
   ```

   **CPU budget** — `--max_cpus N` caps the cores used for concurrency. It is a
   *total* budget shared across concurrently running experiments; each experiment
   consumes `model.n_workers + calibration.n_workers` cores. When unset, all
   detected cores are used (the `cluster` profile defaults it to `8`, or to
   `NXF_MAX_CPUS` if that environment variable is set):
   ```
   nextflow run main.nf --config_file params.yml -profile cluster --max_cpus 16
   ```

4. **Reproducible environments.** Each unit declares its environment in
   `main.nf` (`conda "<unit>/environment.yml"`); how that is resolved is wired in
   `nextflow.config` from flags. Each run picks, per unit, the first that applies:

   | Mode | Flag | What a unit uses |
   | --- | --- | --- |
   | Locked (default) | — | committed `<unit>/lockfile/conda-<platform>.lock` |
   | Unlocked | `--useLockFiles false` | solve `<unit>/environment.yml` at runtime |
   | Containerized | `--containerized` | the unit's image from GHCR, no conda |

   ```
   nextflow run main.nf --config_file params.yml                 # locked
   nextflow run main.nf --config_file params.yml --containerized # images from GHCR
   ```
   - `--lockPlatform` is **auto-detected** from the host
     (`linux-64` | `linux-aarch64` | `osx-64` | `osx-arm64` | `win-64`); override if needed.
   - A unit with no lock for the platform (e.g. `model`/`mcmc`, whose pip-only
     `umbridge` can't survive an explicit lock) falls back to its `environment.yml`.
   - `--condaEngine` is `micromamba` (default), `mamba`, or `conda`.

   Editing a `<unit>/environment.yml` triggers CI (`.github/scripts/update-locks.sh`)
   that re-locks conda-only units and adds a micromamba `Dockerfile` to units that
   can't be locked; a second workflow builds & pushes each unit's image to GHCR
   (`:latest` + `:<sha>`) for `--containerized`.

## Repository structure

Main components:

| Path | What it is |
| --- | --- |
| `main.nf` | Nextflow workflow for a single calibration |
| `experiments.nf` | Nextflow orchestrator for a sweep of experiments |
| `params.yml`, `params-*.yml` | Configs for single runs (one per model variant) |
| `experiments.yml` | Sweep configuration |
| `model/` | **Python** forward model |
| `model_julia/` | **Julia** forward model (Docker / Apptainer) |
| `mcmc/` | MCMC calibration client (`emcee`) |
| `report/`, `diagnostics/` | Generated report and convergence diagnostics |

Supporting units: `pull_data/` (fetch experimental data), `preprocessing/`
(convert raw data to CSV), `experiments/` (generate the sweep), `deterministic_calibration/`
(literature reference coefficients).

<!-- TODO: add an example output figure (e.g. posterior distributions / trace plot from the generated report). -->

## Roadmap

- [x] Add Conda lock files for reproducible environments.
- [ ] Add CI automation.
- [x] Add Nextflow profiles (`local` / `cluster`) to switch the container engine
      between Docker and Apptainer.
- [x] Publish the Julia forward model image to GHCR (multi-arch) and consume it
      from both profiles (Apptainer pulls it via `docker://`).

## Contact

Alan Correa | MBD, RWTH Aachen ([@thealanjason](https://github.com/thealanjason)).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## How to cite

<!-- TODO: add citation for this computational study. -->

## References

- Dirkes, N., & Behr, M. (2026). *A practical computational hemolysis model
  incorporating biophysical properties of the red blood cell membrane.* arXiv.
  https://doi.org/10.48550/arXiv.2601.19994
- Blum, C., Steinseifer, U., & Neidlin, M. (2025). *Toward uncertainty-aware
  hemolysis modeling: A universal approach to address experimental variance.*
  International Journal for Numerical Methods in Biomedical Engineering, 41,
  e70040. https://doi.org/10.1002/cnm.70040
