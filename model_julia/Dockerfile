FROM julia:1.11

ARG ENV_NAME=model

# Environment variables 
ENV JULIA_PROJECT=/opt/${ENV_NAME}
ENV JULIA_DEPOT_PATH=/usr/local/share/.julia
ENV JULIA_HISTORY=/tmp/logs/repl_history.jl


# Install system deps and create directories used by the container
RUN apt-get update \
    && apt-get install -y procps \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/${ENV_NAME} /usr/local/share/.julia /tmp/logs \
    && chmod 0755 /opt/${ENV_NAME} /usr/local/share/.julia /tmp/logs

# Copy the Julia project file into the image 
COPY Project.toml /opt/${ENV_NAME}/Project.toml


# Install the Julia packages defined in Project.toml 
RUN julia -e 'using Pkg; Pkg.instantiate(); Pkg.precompile()'
