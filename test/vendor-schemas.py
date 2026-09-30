#!/usr/bin/env python3
"""Refresh the vendored devcontainer schemas, or check that they are current.

Why vendored rather than fetched at validation time: the two schemas that
matter are self-contained and about 37KB together, so committing them makes
validation work with no network and no SKIP path. The cost is that they can
go stale against upstream, which is what this script exists to catch.

  python3 test/static/vendor-schemas.py --check   # CI: exit 1 if stale
  python3 test/static/vendor-schemas.py          # re-download, update digests

--check compares the committed digest in manifest.json against both the
file on disk and the file upstream, so it catches a tampered copy and an
outdated one. Upstream is tracked from main rather than a pinned tag on
purpose: a devcontainer config that the spec rejects is a build failure in
someone's box, and finding that out in CI is the whole point. Pin to a tag
instead if you would rather never be surprised by an upstream change.
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_DIR = os.path.join(HERE, "schemas")
MANIFEST = os.path.join(SCHEMA_DIR, "manifest.json")


def digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def fetch(url):
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read()


def load_manifest():
    try:
        with open(MANIFEST) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"vendor-schemas FAILED: cannot read {MANIFEST}: {exc}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="verify vendored schemas match upstream, do not write")
    args = ap.parse_args()

    manifest = load_manifest()
    problems = []
    changed = {}

    for name, entry in sorted(manifest["schemas"].items()):
        local_path = os.path.join(SCHEMA_DIR, name)
        if not os.path.isfile(local_path):
            problems.append(f"{name}: vendored file is missing")
            continue

        try:
            upstream = fetch(entry["url"])
        except Exception as exc:  # noqa: BLE001 - any fetch failure is a skip
            print(f"  SKIP {name}: cannot reach upstream ({exc})")
            continue

        up_sha = hashlib.sha256(upstream).hexdigest()
        local_sha = digest(local_path)

        if local_sha != entry["sha256"]:
            problems.append(
                f"{name}: vendored copy does not match the digest in manifest.json "
                f"(on disk {local_sha[:12]}, recorded {entry['sha256'][:12]}); "
                f"it was edited by hand or corrupted"
            )
        if up_sha != entry["sha256"]:
            msg = (f"{name}: upstream has changed since it was vendored "
                   f"(vendored {entry['sha256'][:12]}, upstream {up_sha[:12]})")
            if args.check:
                problems.append(msg + "; run: python3 test/static/vendor-schemas.py")
            else:
                changed[name] = upstream
                print(f"  updating {name} ({entry['sha256'][:12]} -> {up_sha[:12]})")

        try:
            json.loads(upstream)
        except json.JSONDecodeError as exc:
            # Never write a broken schema in: the next validation run would
            # report it as authoritative and every file would fail.
            problems.append(f"{name}: upstream response is not valid JSON ({exc})")

    if args.check:
        if problems:
            print(f"vendor-schemas FAILED ({len(problems)} issue(s)):")
            for p in problems:
                print(f"  - {p}")
            sys.exit(1)
        print(f"vendor-schemas OK: {len(manifest['schemas'])} schema(s) current with upstream")
        return

    if problems:
        print("vendor-schemas FAILED, nothing written:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)

    if not changed:
        print("vendor-schemas: already current")
        return

    for name, blob in changed.items():
        with open(os.path.join(SCHEMA_DIR, name), "wb") as fh:
            fh.write(blob)
        manifest["schemas"][name]["sha256"] = hashlib.sha256(blob).hexdigest()
    with open(MANIFEST, "w") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    print(f"vendor-schemas: refreshed {len(changed)} schema(s)")


if __name__ == "__main__":
    main()
