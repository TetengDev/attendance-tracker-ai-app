#!/usr/bin/env python3
"""Simple ownership check.

Reads ownership.toml in the repo root and ensures every changed file in the
PR is covered by at least one ownership.paths glob. Exits 0 on success, 1 on
failure. Intended to run in CI (checkout at the PR commit).
"""
import os
import sys
import subprocess
import tomllib
from fnmatch import fnmatch

BASE = os.environ.get("BASE","origin/main")

def changed_files():
    # Compare against BASE; assume repo is checked out
    try:
        out = subprocess.check_output(["git", "diff", "--name-only", f"{BASE}...HEAD"]).decode()
    except subprocess.CalledProcessError:
        out = subprocess.check_output(["git", "diff", "--name-only"]).decode()
    return [l.strip() for l in out.splitlines() if l.strip()]


def load_ownership(path="ownership.toml"):
    with open(path, "rb") as f:
        doc = tomllib.load(f)
    lst = doc.get("ownership", [])
    entries = []
    for e in lst:
        entries.append((e.get("issue"), e.get("paths", [])))
    return entries


def main():
    files = changed_files()
    if not files:
        print("No changed files detected — passing ownership check.")
        return 0
    entries = load_ownership()
    uncovered = []
    for f in files:
        ok = False
        for _issue, globs in entries:
            for g in globs:
                if fnmatch(f, g):
                    ok = True
                    break
            if ok:
                break
        if not ok:
            uncovered.append(f)
    if uncovered:
        print("Ownership check failed. The following files are not covered by docs/ownership.toml:")
        for u in uncovered:
            print("  ", u)
        return 1
    print("Ownership check passed — all changed files covered by ownership.toml")
    return 0

if __name__ == '__main__':
    sys.exit(main())
