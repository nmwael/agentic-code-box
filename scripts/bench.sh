#!/usr/bin/env bash
# bench.sh [profile] — measure the active profile (or a given one) and append
# the result to wip/bench-<profile>.jsonl.
#
# Records what the model combos actually cost on this hardware, as opposed to
# the estimates in the investigation thread: peak VRAM after load, load time,
# and generation throughput through the bifrost gateway.
set -euo pipefail

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
STACK_JSON="${STACK_JSON:-/usr/local/share/llm-lab/stack.json}"
BIFROST_PORT="${BIFROST_PORT:-8082}"
ACTIVE_FILE="$ROOT/.devcontainer/active-profile"
OUT_DIR="$ROOT/wip"

command -v jq >/dev/null 2>&1 || {
    echo "ERROR: jq required" >&2
    exit 1
}

if [ $# -ge 1 ]; then
    PROFILE="$1"
elif [ -f "$ACTIVE_FILE" ]; then
    PROFILE="$(cat "$ACTIVE_FILE")"
else
    PROFILE="unknown"
fi

mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/bench-$PROFILE.jsonl"

gpu_mem_mib() {
    nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1
}

echo "[bench] profile: $PROFILE"
[ -f "$STACK_JSON" ] || {
    echo "ERROR: no manifest at $STACK_JSON" >&2
    exit 1
}

TS="$(date -Is)"

jq -n --arg ts "$TS" --arg profile "$PROFILE" --arg stack "$STACK_JSON" \
    --argjson vram "$(gpu_mem_mib || echo 0)" \
    '{ts:$ts, profile:$profile, vram_used_mib:$vram, models:[]}' >/tmp/bench-base.json

count="$(jq '.models | length' "$STACK_JSON")"
i=0
while [ "$i" -lt "$count" ]; do
    name="$(jq -r ".models[$i].name" "$STACK_JSON")"
    port="$(jq -r ".models[$i].port" "$STACK_JSON")"
    ctx="$(jq -r ".models[$i].context" "$STACK_JSON")"

    before="$(gpu_mem_mib || echo 0)"
    if curl -sf -o /dev/null --max-time 2 "http://127.0.0.1:$port/health"; then
        status="up"
    else
        status="down"
    fi
    after="$(gpu_mem_mib || echo 0)"

    tps=""
    if [ "$status" = "up" ]; then
        tps="$(curl -sf --max-time 120 "http://127.0.0.1:$port/v1/completions" \
            -H 'Content-Type: application/json' \
            -d "{\"model\":\"$name\",\"prompt\":\"def fib(n):\",\"max_tokens\":64,\"temperature\":0}" \
            2>/dev/null | jq -r '.timings.predicted_per_second // empty' 2>/dev/null || true)"
    fi

    entry="$(jq -n --arg n "$name" --argjson p "$port" --argjson c "$ctx" \
        --arg s "$status" --argjson b "${before:-0}" --argjson a "${after:-0}" \
        --arg tps "${tps:-}" \
        '{name:$n, port:$p, context:$c, status:$s, vram_before_mib:$b, vram_after_mib:$a, tok_per_s:(if $tps=="" then null else ($tps|tonumber) end)}')"

    jq --argjson e "$entry" '.models += [$e]' /tmp/bench-base.json >/tmp/bench-next.json
    mv /tmp/bench-next.json /tmp/bench-base.json
    i=$((i + 1))
done

jq -c . /tmp/bench-base.json >>"$OUT"
rm -f /tmp/bench-base.json
echo "[bench] appended to $OUT"
cat "$OUT"
