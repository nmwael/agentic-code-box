#!/usr/bin/env bash
# post-create.sh — postCreateCommand. Verifies the box and scaffolds the agent
# payload (AGENTS.md, .opencode/agent, library/) into the workspace. The
# devcontainer features have already installed llama-server, bifrost, opencode
# and the scaffold payload at this point.
set -euo pipefail

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
MODELS_DIR="${MODELS_DIR:-$ROOT/models}"
SCAFFOLD="/usr/local/share/opencode-agents/scaffold.sh"

cd "$ROOT"

echo "[post-create] agentic-code-box"

for bin in git jq llama-server opencode; do
    if command -v "$bin" >/dev/null 2>&1; then
        echo "[post-create] $bin: ready"
    else
        echo "[post-create] $bin: NOT on PATH"
    fi
done

if [ -x "$SCAFFOLD" ]; then
    echo "[post-create] scaffolding agent payload into workspace..."
    WORKSPACE="$ROOT" "$SCAFFOLD" || echo "[post-create] WARNING: scaffold.sh reported an issue"
else
    echo "[post-create] WARNING: $SCAFFOLD not found — agents not installed"
fi

echo "[post-create] weights: $(ls "$MODELS_DIR"/*.gguf 2>/dev/null | wc -l) .gguf in $MODELS_DIR"
if ! ls "$MODELS_DIR"/*.gguf >/dev/null 2>&1; then
    echo "[post-create] no weights yet — run: bash scripts/fetch-models.sh"
fi

echo "[post-create] done. Start the stack with: bash scripts/auto-startup.sh"
