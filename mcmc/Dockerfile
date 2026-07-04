# Auto-generated for a module whose pip deps conda locks can't carry through
# Nextflow; reproduced via a micromamba image built from environment.yml
# instead of a lock file. Build context is the module directory.
FROM mambaorg/micromamba:2.3.1
COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yml /tmp/environment.yml
RUN micromamba install -y -n base -f /tmp/environment.yml \
    && micromamba clean --all --yes
ARG MAMBA_DOCKERFILE_ACTIVATE=1
