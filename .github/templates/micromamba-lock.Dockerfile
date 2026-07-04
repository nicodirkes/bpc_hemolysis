# Image for a lockable module: install the exact pinned conda packages from the
# committed linux-64 explicit lock. Build context is the module's lockfile/ dir.
FROM mambaorg/micromamba:2.3.1
COPY --chown=$MAMBA_USER:$MAMBA_USER conda-linux-64.lock /tmp/lock
RUN micromamba install -y -n base -f /tmp/lock \
    && micromamba clean --all --yes
ARG MAMBA_DOCKERFILE_ACTIVATE=1
