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

## Questions

Reach out to [@thealanjason](https://github.com/thealanjason).
