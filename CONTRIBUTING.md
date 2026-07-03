# Contributing

Thanks for your interest in contributing to this computational study.

## Ways to contribute

- Report a problem or request a change by opening an issue.
- Propose changes via a pull request.

## Development workflow

1. Fork the repository and create a branch for your change.
2. Set up the environment:
   ```
   conda env create -f environment.yml
   conda activate showmehow
   ```
3. Make your change. Keep each computational unit self-contained: its code,
   environment (`environment.yml`), inputs, and outputs should stay together in
   the unit's directory.
4. Verify that the workflow still runs, e.g.:
   ```
   nextflow run main.nf --config_file params.yml
   ```
5. Open a pull request describing what you changed and why.

## Releasing a container image

Containerized units (e.g. `model_julia/`) publish their image to GHCR from a git
tag. Each unit versions independently via a **prefixed** tag so modules don't
share a version line.

Naming: `<module>-v<MAJOR>.<MINOR>.<PATCH>` — e.g. `model-julia-v0.1.0`. The
workflow strips the prefix, so the published image tag is the bare semver
(`ghcr.io/<owner>/<repo>/model_julia:0.1.0`).

Pick one of the following based on your change:
- **PATCH** — rebuild with no behavior change (e.g. refresh the base image).
- **MINOR** — add or update dependencies without changing the model's results.
- **MAJOR** — anything that changes the model's numerics (e.g. bumping the base
  image's major version, or changing a pinned package that affects output).

To cut a release:

1. Edit the module (`Dockerfile`, `Project.toml`, `Manifest.toml`, ...). Opening
   a PR builds the image for **all architectures without pushing**, so a broken
   build is caught in review.
2. After merge, pick the version and tag it:
   ```
   git tag model-julia-v0.1.0
   git push origin model-julia-v0.1.0
   ```
   This builds and pushes the multi-arch image to GHCR.
3. Pin the new tag where the image is consumed — for the Julia model, the
   `container` directive in `main.nf` (`SERVE_MODEL_JL`).

A new containerized module gets its own copy of the workflow
(`.github/workflows/build-<module>-image.yml`), scoped to its directory, with its
own `<module>-v*` tag prefix.

> First publish only: the GHCR package is created private. Make it public once
> (package settings → change visibility) so `docker pull` / `apptainer pull
> docker://` work without credentials.

## Questions

Reach out to [@thealanjason](https://github.com/thealanjason).
