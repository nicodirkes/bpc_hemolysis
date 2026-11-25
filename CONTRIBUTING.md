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

## Container images

Every unit's image is published to GHCR automatically. You never build or tag
one by hand.

To change a unit's environment:

1. Edit its `environment.yml` (Julia units: `Project.toml`).
2. Open a pull request, and after merge the **Lock and build** workflow:
   - updates the lock files, `Dockerfile` or `Manifest.toml`, and commits them
   - builds and pushes the image (`:latest` and `:<sha>`)

Those generated files are overwritten on every run, so don't edit them by hand.

For a Julia unit, the Julia version comes from `[compat] julia` in its
`Project.toml`.

> First publish only: the GHCR package is created private. Make it public once
> (package settings → change visibility) so `docker pull` / `apptainer pull
> docker://` work without credentials.

## Questions

Reach out to [@thealanjason](https://github.com/thealanjason).
