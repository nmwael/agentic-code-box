# agentic-code-box

A ready-to-run agentic devcontainer built entirely on
[`agentic-devcontainer-feature`](https://github.com/nmwael/agentic-devcontainer-feature).
No models are baked into the image — weights are fetched at container-create time
into the bind-mounted workspace, so rebuilding is fast and you can swap models
without a rebuild.

## Why there are three profiles

The original B/D suggestions were built for a 24 GB card. On the target box
(**RTX 5070, 12227 MiB VRAM, 15 GB RAM**) their real artifact sizes are:

| Profile | Original weights | Fits? |
| --- | --- | --- |
| B | Gemma 4 26B `UD-IQ2_M` + DeepSeek-Coder 6.7B `IQ4_XS` = **12.64 GiB** | No |
| D | Gemma 4 12B `UD-IQ3_M` + Phi-4 `IQ4_NL` = **12.13 GiB** | No |

Both exceed available VRAM, and neither leaves room for KV cache or two CUDA
contexts. Every profile below is re-quantized to fit. All six model URLs
return HTTP 200, and every model was loaded and sanity-checked on the target GPU.

| Profile | Orchestrator (:8089) | Coder (:8090) | Weights (measured) | VRAM used | Free after |
| --- | --- | --- | --- | --- | --- |
| `b` | Gemma 4 12B `UD-IQ3_XXS` | Qwen2.5-Coder-3B `Q4_K_M` | **6.28 GiB** | 8140 MiB | ~2780 MiB |
| `d` | Gemma 4 12B `UD-IQ2_M` | Phi-4 `IQ3_M` | **9.94 GiB** | 10784 MiB | ~320 MiB |
| `q` | Qwen3-8B `Q4_K_M` | Qwen2.5-Coder-7B `Q4_K_M` | **9.04 GiB** | 10936 MiB | ~400 MiB |

`b` is the default and by far the most comfortable. `q` is the strongest
coder. `d` is the closest thing to a "Phi-4 coder" setup and is the tightest —
close other GPU workloads before booting it.

### KV cache is the real constraint, not weights

Weight sizes alone are misleading. A single 12B model at the naive
`ctx=32768, parallel=3, f16 KV` setting needs **8148 MiB** — nearly twice its
own weights — because KV cache scales with context x slots. All three profiles
as first written (f16 KV, 3/2 slots) needed **~17.8 GiB** and could not run at
all. Every profile therefore ships quantized KV:

- Orchestrator: `ctx=16384`, `--cache-type-k q8_0 --cache-type-v q8_0`
- Coder: `ctx=8192`, `--cache-type-k q4_0 --cache-type-v q8_0`

Measured effect on the coder: KV 16384 MiB -> 1664 MiB, compute buffer
808 MiB -> 168 MiB, total 9699 MiB -> 5397 MiB. `auto-startup.sh` passes
`kv_cache_type_k` / `kv_cache_type_v` through from the profile when present.

The orchestrator keeps `parallel: 3` in profile `b` because `roles-b.json` maps
roles onto slots 0/1/2; each extra slot costs only ~250 MiB since Gemma 4's KV
is small (255 MiB at 1 slot, 765 MiB at 3). The coder runs `parallel: 1`.

Profiles `d` and `q` are too tight for that and run `parallel: 1`, so every role
there shares slot 0 — three slots would need ~510 MiB more in `d` and ~2450 MiB
more in `q`, and both already have under 500 MiB free. If you want per-role
slots in `d`/`q`, drop their orchestrator context to 8192 first and re-measure.

### Model choices verified on hardware

Each model was loaded on the RTX 5070 and asked "What is the capital of
France?" over `/v1/chat/completions`. Five of six are coherent — including
`IQ2_M`, which is far more aggressive than its name suggests.

Slot routing uses the `slot_id` request field; there is no `/slot/N` URL path
in llama.cpp b11223. `gemma-4-12b` is a reasoning model, so it fills
`reasoning_content` first and only then `content` — raise `max_tokens` or
clients will see an empty reply.

#### DeepSeek-Coder 6.7B: usable, but not without a stop-string change

`IQ4_XS` and `Q4_K_M` from `RichardErkhov/deepseek-ai_-_deepseek-coder-6.7b-instruct-gguf`
both return empty or degenerate output (`defdefdef...`). That is **not** a
quantization failure — the identical `Q4_K_M` from `TheBloke/deepseek-coder-6.7B-instruct-GGUF`
answers correctly. The RichardErkhov GGUFs carry broken chat-template metadata.

TheBloke's version still never stops: it emits `<|im_end|>` and `<|im_start|>`
as literal text and keeps generating, because the tokenizer does not mark them
as stop tokens. Findings:

- An explicit ChatML `--chat-template-file` does **not** fix it.
- Request-level `"stop": ["<|im_end|>", "<|im_start|>"]` does fix it — clean
  `finish: stop` for both prose and code.
- `llama-server` has no server-side `--stop` flag, and neither the opencode
  provider generator nor the bifrost template has a stop passthrough, so every
  client would have to send those strings. That is a feature-side change, and
  at 3.80 GiB it would also cut profile `b` to ~294 MiB of free VRAM.

Profile `b` therefore uses Qwen2.5-Coder-3B `Q4_K_M`, which works out of the
box and leaves ~2780 MiB free. Revisit this if a stop-passthrough is ever added
to the stack.

## Boot

```bash
devcontainer up --workspace-folder .
```

Startup order is deliberate: the `models` feature must install **before**
`bifrost-gateway`, because bifrost materializes its routing config from the
manifest at build time. That ordering is enforced via
`overrideFeatureInstallOrder` in `.devcontainer/devcontainer.json`.

On first create, `postCreateCommand` fetches the weights, generates
`opencode.json`, and scaffolds the agent definitions. Weights land in `models/`
(11 GB for `b`), which is gitignored.

## Switching profiles

```bash
bash scripts/use-profile.sh d      # or b / q
```

This writes the new profile, regenerates `stack.json`, `bifrost.json` and
`opencode.json`, and re-fetches any missing weights. Downloads are idempotent,
so switching back and forth does not re-download.

Two important details:

- The `models` feature reads `.devcontainer/llm-lab-models.json` at **build**
  time, so a plain container restart keeps the old profile. Run
  `devcontainer up --workspace-folder .` to make the change the built-in default.
- `use-profile.sh` applies the profile to the *running* container immediately,
  so `bash scripts/auto-startup.sh` will use the new models without a rebuild.

The active profile is recorded in `.devcontainer/active-profile`.

## Ports

| Port | Service |
| --- | --- |
| 8089 | orchestrator `llama-server` |
| 8090 | coder `llama-server` |
| 8082 | bifrost gateway |
| 4096 | opencode |

## Benchmarking

```bash
bash scripts/bench.sh        # or: bash scripts/bench.sh d
```

Writes `wip/bench-<profile>.json` and prints total VRAM, per-model VRAM
occupancy, and a short completion's prompt/eval throughput. Useful for
confirming a profile actually fits before committing to it.

## Layout

```
.devcontainer/
  devcontainer.json        feature graph, install order, ports, lifecycle hooks
  llm-lab-models.json      active model list (build-time input to the feature)
  llm-lab-roles.json       active agent -> model/slot mapping
  active-profile           which profile is current
profiles/
  combo-{b,d,q}.json       model lists per profile
  roles-{b,d,q}.json       role mappings per profile
scripts/
  use-profile.sh           switch profiles (build + runtime)
  fetch-models.sh          re-fetch weights, skipping what exists
  auto-startup.sh          llama-server(s) + bifrost + opencode
  post-create.sh           first-run fetch, config generation, scaffold
  bench.sh                 VRAM + throughput measurement
```

`AGENTS.md` / `AGENTS_LIFECYCLE.md` are intentionally **not** committed. The
feature's scaffold step skips generating them when they already exist, so
committing placeholders would suppress the real agent definitions.

## Notes on model downloads

Model files are fetched with `curl --fail` and are validated as GGUF before
being accepted. A Hugging Face error page or rate-limit response is deleted and
retried rather than cached, otherwise the idempotency check would treat the
junk file as a finished download and never recover.
