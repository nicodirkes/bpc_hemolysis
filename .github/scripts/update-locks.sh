#!/usr/bin/env bash
# Keep each conda module's reproducible build recipe current. For every module
# (a dir with an environment.yml, excluding the root dev env):
#   - no pip deps  -> lockable: regenerate per-platform explicit locks under
#                     <module>/lockfile/ (what Nextflow's conda directive reads).
#   - has pip deps -> not lockable (explicit locks silently drop pip): ensure the
#                     module ships a micromamba Dockerfile instead.
# Requires conda-lock on PATH. Run from the repo root.
set -euo pipefail

platforms="linux-64 linux-aarch64 osx-64 osx-arm64 win-64"
template=".github/templates/micromamba-env.Dockerfile"

for env in $(find . -mindepth 2 -maxdepth 2 -name environment.yml | sort); do
  m=$(dirname "$env"); m=${m#./}
  if grep -q 'pip:' "$env"; then
    echo "[$m] pip deps -> Dockerfile"
    rm -rf "$m/lockfile"
    [ -f "$m/Dockerfile" ] || cp "$template" "$m/Dockerfile"
  else
    echo "[$m] conda-only -> locks"
    mkdir -p "$m/lockfile"
    for p in $platforms; do
      conda-lock -f "$env" -p "$p" --kind explicit \
        --filename-template "$m/lockfile/conda-{platform}.lock"
    done
  fi
done
