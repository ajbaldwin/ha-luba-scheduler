#!/usr/bin/env bash
set -euo pipefail
docker build -f Dockerfile.test -t luba-test .
docker run --rm luba-test python -m pytest "$@"
