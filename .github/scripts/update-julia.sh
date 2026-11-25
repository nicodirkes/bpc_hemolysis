#!/usr/bin/env bash
# For every Julia module (a dir with a Project.toml): write its Dockerfile from the
# template (Julia version = [compat] julia in Project.toml) and resolve Manifest.toml
# with that same Julia image. Requires docker. Run from the repo root.
set -euo pipefail

for proj in $(find . -mindepth 2 -maxdepth 2 -name Project.toml | sort); do
  m=$(dirname "$proj"); m=${m#./}
  v=$(sed -n 's/^julia *= *"\([^"]*\)".*/\1/p' "$proj")
  [ -n "$v" ] || { echo "[$m] Project.toml needs [compat] julia = \"X.Y\"" >&2; exit 1; }
  echo "[$m] julia $v -> Dockerfile + Manifest.toml"
  sed -e "s/@JULIA_VERSION@/$v/" -e "s/@UNIT@/$m/g" .github/templates/julia.Dockerfile > "$m/Dockerfile"
  docker run --rm -v "$PWD/$m":/w -e JULIA_DEPOT_PATH=/tmp/depot "julia:$v" \
    julia --project=/w -e 'using Pkg; Pkg.Registry.add("General"); Pkg.resolve()'
done
