#!/usr/bin/env bash
# Creates the underscore-named symlinks `adk web` needs to discover this
# repo's agent apps.
#
# ADK's agent_loader.py hard-requires the app directory basename to be a
# valid Python identifier (letters, digits, underscores only) -- checked
# unconditionally in _validate_agent_name(), regardless of whether the app
# is discovered via agent.py or root_agent.yaml. This repo's real
# directories, posgmo-factory/ and prd-builder/, both have hyphens and so
# can never be selected directly in the dev UI ("No root_agent found" /
# "Invalid agent name"). A symlink with an underscore name resolves this
# without renaming the real directories (which many hardcoded absolute
# paths throughout the codebase reference).
#
# Run once per clone/machine from the repo root:
#   posgmo-factory/scripts/setup_dev_ui.sh
# Then: adk web  (select "posgmo_factory" or "prd_builder" from the dropdown)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

link_pair() {
  local real="$1" link="$2"
  if [ ! -d "$real" ]; then
    echo "skip: $real not found" >&2
    return
  fi
  if [ -L "$link" ]; then
    echo "ok: $link already linked -> $(readlink "$link")"
    return
  fi
  if [ -e "$link" ]; then
    echo "skip: $link exists and is not a symlink -- resolve manually" >&2
    return
  fi
  ln -s "$real" "$REPO_ROOT/$link"
  echo "created: $link -> $real"
}

link_pair "posgmo-factory" "posgmo_factory"
link_pair "prd-builder" "prd_builder"
