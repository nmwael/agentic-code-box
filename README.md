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
contexts. Every profile below is re-quantized to fit, with a small headroom
margin kept free. Every model URL was verified to return HTTP 200.

| Profile | Orchestrator (:8089) | Coder (:8090) | Weights |
| --- | --- | --- | --- |
| `b` | Gemma 4 12B `UD-IQ3_XXS` | DeepSeek-Coder 6.7B `IQ4_XS` | **7.72 GiB** |
| `d` | Gemma 4 12B `UD-IQ2_M` | Phi-4 `IQ3_M` | **10.35 GiB** |
| `q` | Qwen3-8B `Q4_K_M` | Qwen2.5-Coder-7B `Q4_K_M` | **9.05 GiB** |

`b` is the default (best quality-to-VRAM ratio). `d` is the closest thing to a
"Phi-4 coder" setup and runs the largest models, so it is the tightest on VRAM.
`q` is the safest if you also want headroom for other GPU work.

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
