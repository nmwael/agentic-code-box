#!/usr/bin/env bash
# use-profile.sh <b|d|q> — switch the active LLM profile.
#
# Rewrites the models feature's input files, re-materializes the two derived
# configs (bifrost upstreams, opencode providers) from the shared manifest, and
# restarts the servers. The manifest is the single source of truth: everything
# else is regenerated from it so the model-id <-> --alias <-> bifrost routing
# prefix cannot drift apart.
set -euo pipefail

PROFILE="${1:-}"
ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
STACK="${STACK_JSON:-/usr/local/share/llm-lab/stack.json}"
MODELS_FILE="$ROOT/.devcontainer/llm-lab-models.json"
ROLES_FILE="$ROOT/.devcontainer/llm-lab-roles.json"
ACTIVE_FILE="$ROOT/.devcontainer/active-profile"

die() {
    echo "ERROR: $*" >&2
    exit 1
}

case "$PROFILE" in
b | d | q) ;;
*) die "usage: bash scripts/use-profile.sh <b|d|q>" ;;
esac

command -v jq >/dev/null 2>&1 || die "jq is required (apt-get-packages feature)"

MODELS_SRC="$ROOT/profiles/combo-$PROFILE.json"
ROLES_SRC="$ROOT/profiles/roles-$PROFILE.json"
[ -f "$MODELS_SRC" ] || die "missing $MODELS_SRC"
[ -f "$ROLES_SRC" ] || die "missing $ROLES_SRC"

# --- Stop the currently running llama-servers ---------------------------------
# They hold VRAM; a stale server on :8089 would collide with the new profile.
for port in 8089 8090; do
    if curl -sf -o /dev/null --max-time 2 "http://127.0.0.1:$port/health" 2>/dev/null; then
        pid="$(pgrep -f "llama-server.*--port $port" | head -1 || true)"
        echo "[use-profile] stopping llama-server on :$port${pid:+ (pid $pid)}"
        [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
    fi
done
sleep 2

# --- Rewrite the feature input files ------------------------------------------
mkdir -p "$ROOT/.devcontainer"
cp -f "$MODELS_SRC" "$MODELS_FILE"
cp -f "$ROLES_SRC" "$ROLES_FILE"
printf '%s\n' "$PROFILE" >"$ACTIVE_FILE"
echo "[use-profile] profile '$PROFILE' written to .devcontainer/llm-lab-{models,roles}.json"
echo "[use-profile] NOTE: the models feature reads these at BUILD time — run"
echo "[use-profile]       'devcontainer up --workspace-folder .' to apply."
echo "[use-profile]       Applying to the running container now (no rebuild):"

# --- Rebuild stack.json from the profile (the same shape install.sh writes) ----
if [ -f "$STACK" ]; then
    jq -n \
        --argjson m "$(jq -c . "$MODELS_FILE")" \
        --argjson r "$(jq -c . "$ROLES_FILE")" \
        --arg md "${MODELS_DIR:-$ROOT/models}" \
        '{
            schema: 1,
            notation: "roles -> (model, slot); model id = provider/name[-s{slot}]",
            models_dir: $md,
            bifrost_port: 8082,
            opencode_port: 4096,
            subagent_depth: 2,
            cloud: false,
            cloud_provider: "opencode",
            models: $m,
            roles: $r
        }' >"$STACK"
    echo "[use-profile] rewrote $STACK"
else
    die "no manifest at $STACK — the models feature has not run yet (container not built)"
fi

# --- Regenerate the derived configs -------------------------------------------
BF="/usr/local/share/llm-lab/bifrost"
if [ -x "$BF/write-bifrost-config.sh" ]; then
    "$BF/write-bifrost-config.sh" "$STACK" "$BF/config/bifrost.json" 8089
else
    echo "[use-profile] WARNING: write-bifrost-config.sh not found — bifrost routing stale"
fi

OA="/usr/local/share/opencode-agents"
if [ -x "$OA/generate-opencode.sh" ]; then
    sh "$OA/generate-opencode.sh" "$STACK" "$ROOT/opencode.json"
else
    echo "[use-profile] WARNING: generate-opencode.sh not found — opencode.json stale"
fi

# --- Fetch any newly-referenced weights ----------------------------------------
if [ -x /usr/local/share/llm-lab/models/fetch-models.sh ]; then
    echo "[use-profile] fetching model weights (idempotent, skips existing files)..."
    /usr/local/share/llm-lab/models/fetch-models.sh
else
    echo "[use-profile] WARNING: fetch-models.sh not found — install models manually"
fi

echo "[use-profile] done. Start the stack with: bash scripts/auto-startup.sh"
