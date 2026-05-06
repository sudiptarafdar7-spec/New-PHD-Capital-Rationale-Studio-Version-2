#!/bin/bash
# Post-merge setup for PHD Capital Rationale Studio.
# Runs after a task is merged to refresh JS dependencies. Idempotent.
# Python dependencies are managed by Nix/uv and installed via the
# package management tool, not pip — pip would fail against the
# immutable /nix/store. If a merge introduces new Python packages,
# install them via the package manager separately.
set -e

if [ -f package.json ]; then
  npm install --no-audit --no-fund
fi
