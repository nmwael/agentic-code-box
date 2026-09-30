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


def main():
    try:
        with open(CONFIG) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"check-feature-order FAILED: {CONFIG}: {exc}")
        return 1

    errors = []
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

    print(f"check-feature-order OK: {len(order)} feature(s) ordered explicitly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
