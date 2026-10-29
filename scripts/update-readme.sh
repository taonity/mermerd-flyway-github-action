#!/bin/bash
set -euo pipefail

# Updates the generated diagram in a README file between
# <!-- mermerd-start --> and <!-- mermerd-end --> markers.
#
# Usage: bash scripts/update-readme.sh <readme_path> <schema_json_or_mmd> [formatter flags]

README_PATH="${1:?Usage: $0 <readme_path> <schema_json_or_mmd>}"
SCHEMA_OUTPUT="${2:?Usage: $0 <readme_path> <schema_json_or_mmd>}"

shift 2
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/format-mermaid.py" "$SCHEMA_OUTPUT" --readme "$README_PATH" "$@"
