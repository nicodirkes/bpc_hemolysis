# Image for a lockable module: install the exact pinned conda packages from the
# committed linux-64 explicit lock. Build context is the module's lockfile/ dir.
FROM mambaorg/micromamba:2.3.1
# procps: `ps` is needed by Nextflow for task metrics/reports
USER root
RUN apt-get update && apt-get install -y procps && rm -rf /var/lib/apt/lists/*
USER $MAMBA_USER
COPY --chown=$MAMBA_USER:$MAMBA_USER conda-linux-64.lock /tmp/lock
RUN micromamba install -y -n base -f /tmp/lock \
    && micromamba clean --all --yes
# Env on PATH without the entrypoint (Apptainer doesn't run it)
ENV PATH=/opt/conda/bin:$PATH
ARG MAMBA_DOCKERFILE_ACTIVATE=1
