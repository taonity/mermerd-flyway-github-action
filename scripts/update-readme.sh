#!/bin/bash
set -euo pipefail

# Updates a mermaid diagram block in a README file between
# <!-- mermerd-start --> and <!-- mermerd-end --> markers.
#
# Usage: ./update-readme.sh <readme_path> <mermerd_output_file>

README_PATH="${1:?Usage: $0 <readme_path> <mermerd_output_file>}"
MERMERD_OUTPUT="${2:?Usage: $0 <readme_path> <mermerd_output_file>}"

if [ ! -f "$README_PATH" ]; then
  echo "Error: README file not found: $README_PATH" >&2
  exit 1
fi

if [ ! -f "$MERMERD_OUTPUT" ]; then
  echo "Error: Mermerd output file not found: $MERMERD_OUTPUT" >&2
  exit 1
fi

if ! grep -q '<!-- mermerd-start -->' "$README_PATH"; then
  echo "Error: Marker <!-- mermerd-start --> not found in $README_PATH" >&2
  exit 1
fi

if ! grep -q '<!-- mermerd-end -->' "$README_PATH"; then
  echo "Error: Marker <!-- mermerd-end --> not found in $README_PATH" >&2
  exit 1
fi

awk -v output="$MERMERD_OUTPUT" '
  /<!-- mermerd-start -->/ {
    print
    while ((getline line < output) > 0) print line
    skip = 1
    next
  }
  /<!-- mermerd-end -->/ {
    skip = 0
    print
    next
  }
  !skip
' "$README_PATH" > "${README_PATH}.tmp"

mv "${README_PATH}.tmp" "$README_PATH"
echo "Successfully updated mermaid diagram in $README_PATH"
