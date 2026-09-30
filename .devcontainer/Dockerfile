# syntax=docker/dockerfile:1
#
# Backing image for agentic-code-box.
#
# The base exists for one reason: the llama-server feature installs a CPU-only
# build by default. Upstream's llama-<v>-bin-ubuntu-x64 release asset ships no
# libggml-cuda.so at all, so `llama-server --list-devices` reports "(none)" and
# the libcudart/libcublas libraries bundled alongside it go completely unused.
# No Linux CUDA asset is published for that release line — the only CUDA
# artifacts are Windows zips.
#
# The official ghcr.io/ggml-org/llama.cpp server-cuda image does ship real CUDA
# kernels. Verified with cuobjdump rather than assumed: its libggml-cuda.so
# contains sm_120a SASS cubins (Blackwell — this box is an RTX 5070,
# compute_cap 12.0) plus PTX for sm_50..sm_90 as a JIT fallback.
#
# It is built against CUDA 12.8, so the base is aligned to 12.8.1 to match; the
# 13.3 line has no prebuilt equivalent. Pinned by digest because a floating tag
# would silently swap the GPU binary out from under a rebuild.

FROM ghcr.io/ggml-org/llama.cpp@sha256:5d0812fe45cb5dcb4ac5c588148a601aca63b6b224601f8d1f6f01fdfb07a111 AS llamacpp

FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

# libgomp1 — the prebuilt ggml libraries are OpenMP-linked exactly like the
# release build, and libgomp1 is a separate package from libgcc-s1. Without it
# every binary dies with:
#   error while loading shared libraries: libgomp.so.1
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Flatten into /opt/llama-server. Two reasons this exact path matters:
#   1. the llama-server feature checks for /opt/llama-server/llama-server and
#      no-ops when present ("custom image as base"). Without this the feature
#      would install the CPU build over the top and silently shadow the GPU one;
#   2. it keeps the feature's documented install layout intact.
COPY --from=llamacpp /app/ /opt/llama-server/

# Library resolution. The upstream binary carries RUNPATH="/app/build/bin:" —
# a build-time path that does not exist in the finished image, with a trailing
# colon that the loader reads as an empty entry, i.e. "also search the current
# working directory". Upstream only works because its WORKDIR is /app, so it
# breaks the moment anything runs it from another directory. Registering the
# directory with ldconfig makes it cwd-independent instead of relying on that.
RUN echo /opt/llama-server > /etc/ld.so.conf.d/llama-server.conf \
    && ln -sf /opt/llama-server/llama-server /usr/local/bin/llama-server \
    && ldconfig

# Fail the image build here rather than at the first agent prompt. Loading the
# binary is the only way to prove every transitive shared object resolved.
# Run from / as well: the upstream image's own layout would pass from its
# WORKDIR and fail here if the ldconfig fix above regressed.
RUN cd / && /opt/llama-server/llama-server --version

# Where model weights are fetched. Bind-mounted from the host, so it is not
# part of the image.
ENV MODELS_DIR=/workspaces/agentic-code-box/models
RUN mkdir -p "$MODELS_DIR"

# JSON Schema CLI, for test/. Pinned to the version CI installs so a local run
# and a CI run cannot disagree on a gate.
RUN npm install -g @sourcemeta/jsonschema@17.0.0 \
    && jsonschema version
