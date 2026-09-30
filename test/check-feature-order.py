#!/usr/bin/env python3
"""Guard the overrideFeatureInstallOrder contract in .devcontainer/devcontainer.json.

Two rules, both learned the hard way:

1. Every entry must be an exact key in "features". Given a bare name like
   "apt-get-packages", the CLI resolves it as a *legacy* feature from the default
   collection and hard-fails before any feature installs:

       Legacy feature 'apt-get-packages' not supported.

   That is an unbootable box, and the shorthand looked harmless.

2. The list must name every feature, so the order stays explicit. The
   `models` -> `bifrost-gateway` edge is the load-bearing one: bifrost
   materializes its routing config from the manifest that `models` writes, so
   installing bifrost first leaves it routing to nothing.

This repo previously shipped the shorthand and could not boot. Nothing here
catches a regression except actually running `devcontainer up`, which is slow
and needs a GPU, so this check is the cheap gate.

Pure Python 3 stdlib: no network, no jq, no pip. Exit 0 when the config is
sound, 1 otherwise.
"""
import json
import os
import sys

CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".devcontainer",
    "devcontainer.json",
)

# Order-sensitive: bifrost needs the manifest that `models` writes.
MUST_PRECEDE = [
    ("ghcr.io/nmwael/agentic-devcontainer-feature/models",
     "ghcr.io/nmwael/agentic-devcontainer-feature/bifrost-gateway"),
]

# Booleans, per the devcontainer schema. bool is a subclass of int in Python,
# so these are checked ahead of any int test or 1 and 0 would pass.
BOOL_FIELDS = ("privileged", "init", "updateRemoteUserUID")
STR_FIELDS = ("remoteUser", "workspaceFolder")
STR_ARRAYS = ("capAdd", "securityOpt", "runArgs")
USER_ENV_PROBES = ("none", "loginShell", "loginInteractiveShell", "interactiveShell")


def check_types(data):
    """Type-check the devcontainer fields this config sets.

    Transcribed from devContainer.base.schema.json by hand so this stays
    runnable offline, like the rest of the check. Covers the fields present
    here, not the whole spec.

    Added because a wrong value in this file is invisible to every other
    tool in the loop. The permissive CLI reads a bad hostRequirements.gpu,
    decides it is a string, and returns it without complaint; the stricter
    CLI bundled with VS Code rejects it outright. This repo is built through
    VS Code, so the strict one is the one that matters and the permissive
    one is the one that runs in CI.
    """
    out = []
    for key in BOOL_FIELDS:
        if key in data and not isinstance(data[key], bool):
            out.append(
                f"'{key}' must be a boolean, got {type(data[key]).__name__} "
                f"({data[key]!r})"
            )
    for key in STR_FIELDS:
        if key in data and not isinstance(data[key], str):
            out.append(f"'{key}' must be a string, got {type(data[key]).__name__}")
    for key in STR_ARRAYS:
        val = data.get(key)
        if val is None:
            continue
        if not isinstance(val, list) or not all(isinstance(v, str) for v in val):
            out.append(f"'{key}' must be an array of strings")

    ports = data.get("forwardPorts")
    if ports is not None:
        if not isinstance(ports, list):
            out.append("'forwardPorts' must be an array")
        else:
            for p in ports:
                if isinstance(p, bool) or not isinstance(p, (int, str)):
                    out.append(
                        f"'forwardPorts' entry {p!r} must be an integer or a "
                        f"'host:port' string"
                    )
                elif isinstance(p, int) and not (0 <= p <= 65535):
                    out.append(f"'forwardPorts' entry {p} is outside 0-65535")

    env = data.get("containerEnv")
    if env is not None:
        if not isinstance(env, dict):
            out.append("'containerEnv' must be an object")
        else:
            for k, v in env.items():
                if not isinstance(v, str):
                    out.append(
                        f"'containerEnv' value for '{k}' must be a string, got "
                        f"{type(v).__name__}"
                    )

    req = data.get("hostRequirements")
    if req is not None:
        if not isinstance(req, dict):
            out.append("'hostRequirements' must be an object")
        else:
            if "gpu" in req:
                gpu = req["gpu"]
                # bool before int: True/False are ints in Python.
                if not (isinstance(gpu, bool) or gpu == "optional"
                        or isinstance(gpu, dict)):
                    out.append(
                        f'hostRequirements.gpu must be true, false, "optional", or '
                        f'an object; got {gpu!r}. Note "all" is the Docker --gpus '
                        f"spelling and is not valid for this field"
                    )
            if "cpus" in req and (isinstance(req["cpus"], bool)
                                  or not isinstance(req["cpus"], int)):
                out.append("'hostRequirements.cpus' must be an integer")
            for key in ("memory", "storage"):
                if key in req and not isinstance(req[key], str):
                    out.append(f"'hostRequirements.{key}' must be a string")

    probe = data.get("userEnvProbe")
    if probe is not None and probe not in USER_ENV_PROBES:
        out.append(f"'userEnvProbe' has invalid value {probe!r}")

    return out


def main():
    try:
        with open(CONFIG) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"check-feature-order FAILED: {CONFIG}: {exc}")
        return 1

    errors = check_types(data)
    features = data.get("features") or {}
    order = data.get("overrideFeatureInstallOrder")

    if order is None:
        errors.append(
            "overrideFeatureInstallOrder is absent; the models -> bifrost-gateway "
            "ordering is load-bearing and must be stated explicitly"
        )
    else:
        for entry in order:
            if entry not in features:
                errors.append(
                    f"overrideFeatureInstallOrder entry '{entry}' is not a key in "
                    "'features'; the CLI treats a bare name as a legacy feature and "
                    "aborts the build. Use the full OCI ref."
                )
        for missing in sorted(set(features) - set(order)):
            errors.append(
                f"overrideFeatureInstallOrder omits '{missing}'; list every feature "
                "so the install order stays explicit and complete"
            )
        for earlier, later in MUST_PRECEDE:
            if earlier in order and later in order and order.index(earlier) > order.index(later):
                errors.append(
                    f"'{earlier}' must install before '{later}'; bifrost reads the "
                    "manifest that models writes at build time"
                )

    if errors:
        print(f"check-feature-order FAILED ({len(errors)} issue(s)):")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(f"check-feature-order OK: config types valid, {len(order)} feature(s) ordered explicitly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
