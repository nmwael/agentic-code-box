#!/usr/bin/env bash
# fetch-models.sh — download the active profile's GGUF weights into models/.
#
# Thin wrapper over the models feature's fetcher, which reads stack.json (or
# models.json) and honours the per-model `url` field added in feature 1.3.0.
# The feature is the single source of truth for how a model is located, so this
# script only sets MODELS_DIR and delegates.
set -euo pipefail

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
FETCHER="/usr/local/share/llm-lab/models/fetch-models.sh"

if [ ! -x "$FETCHER" ]; then
    echo "ERROR: $FETCHER not found — is the models feature installed?" >&2
    exit 1
fi

export MODELS_DIR="${MODELS_DIR:-$ROOT/models}"
mkdir -p "$MODELS_DIR"

echo "[fetch-models] target: $MODELS_DIR"
"$FETCHER"
echo "[fetch-models] done."
