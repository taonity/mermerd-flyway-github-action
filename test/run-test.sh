#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

MERMERD_VERSION="${MERMERD_VERSION:-0.13.0}"
MERMERD_CONFIG="$SCRIPT_DIR/mermerd.yaml"
MERMERD_BIN="$PROJECT_DIR/bin/mermerd"
SCHEMA_GENERATOR="${SCHEMA_GENERATOR:-tbls}"
TBLS_VERSION="${TBLS_VERSION:-1.96.1}"
TBLS_BIN="$PROJECT_DIR/bin/tbls-$TBLS_VERSION"
OUTPUT_DIR="${OUTPUT_DIR:-$PROJECT_DIR/test/output}"
case "$SCHEMA_GENERATOR" in
  tbls|mermerd) ;;
  *) echo 'SCHEMA_GENERATOR must be tbls or mermerd' >&2; exit 1 ;;
esac
mkdir -p "$OUTPUT_DIR"

export DB_NAME="${DB_NAME:-mermerd_db}"
export WORKSPACE_PATH="${WORKSPACE_PATH:-$PROJECT_DIR}"
export FLYWAY_LOCATIONS="${FLYWAY_LOCATIONS:-filesystem:/workspace/test/sql}"

cleanup() {
  echo "Cleaning up..."
  docker compose -f "$PROJECT_DIR/docker-compose.yml" down -v 2>/dev/null || true
}
trap cleanup EXIT

echo "==> Starting PostgreSQL and running Flyway migrations..."
docker compose -f "$PROJECT_DIR/docker-compose.yml" up -d postgres

FLYWAY_ENV_ARGS=()

if [ -n "${FLYWAY_PLACEHOLDER_PREFIX:-}" ]; then
  FLYWAY_ENV_ARGS+=(-e "FLYWAY_PLACEHOLDER_PREFIX=$FLYWAY_PLACEHOLDER_PREFIX")
fi

if [ -n "${FLYWAY_PLACEHOLDER_SUFFIX:-}" ]; then
  FLYWAY_ENV_ARGS+=(-e "FLYWAY_PLACEHOLDER_SUFFIX=$FLYWAY_PLACEHOLDER_SUFFIX")
fi

if [ -n "${FLYWAY_PLACEHOLDERS:-}" ]; then
  IFS=',' read -ra PAIRS <<< "$FLYWAY_PLACEHOLDERS"
  for pair in "${PAIRS[@]}"; do
    key=$(echo "$pair" | cut -d= -f1 | xargs | tr '[:lower:]' '[:upper:]')
    value=$(echo "$pair" | cut -d= -f2- | xargs)
    FLYWAY_ENV_ARGS+=(-e "FLYWAY_PLACEHOLDERS_${key}=${value}")
  done
fi

docker compose -f "$PROJECT_DIR/docker-compose.yml" run --rm "${FLYWAY_ENV_ARGS[@]}" flyway

if [ "$SCHEMA_GENERATOR" = tbls ]; then
  echo "==> Exporting schema with tbls v${TBLS_VERSION}..."
  if [ ! -x "$TBLS_BIN" ]; then
    mkdir -p "$PROJECT_DIR/bin"
    curl -fsSL "https://github.com/k1LoW/tbls/releases/download/v${TBLS_VERSION}/tbls_v${TBLS_VERSION}_linux_amd64.tar.gz" \
      | tar xz -C "$PROJECT_DIR/bin" tbls
    mv "$PROJECT_DIR/bin/tbls" "$TBLS_BIN"
    chmod +x "$TBLS_BIN"
  fi
  SCHEMA_PATH="$OUTPUT_DIR/schema.json"
  "$TBLS_BIN" out "postgres://mermerd:mermerd@localhost:5432/${DB_NAME}?sslmode=disable" \
    --include 'public.*' --format json --out "$SCHEMA_PATH"
else
  echo "==> Downloading mermerd v${MERMERD_VERSION}..."
  if [ ! -x "$MERMERD_BIN" ]; then
    mkdir -p "$(dirname "$MERMERD_BIN")"
    curl -fsSL "https://github.com/KarnerTh/mermerd/releases/download/v${MERMERD_VERSION}/mermerd_${MERMERD_VERSION}_linux_amd64.tar.gz" \
      | tar xz -C "$(dirname "$MERMERD_BIN")" mermerd
    chmod +x "$MERMERD_BIN"
  fi
  echo "==> Running mermerd with $MERMERD_CONFIG..."
  "$MERMERD_BIN" --runConfig "$MERMERD_CONFIG"
  SCHEMA_PATH=/tmp/mermerd-output.mmd
fi

echo "==> Formatting native Mermaid Markdown..."
printf '# Database schema\n\n<!-- mermerd-start -->\n<!-- mermerd-end -->\n' > "$OUTPUT_DIR/README.md"
python3 "$PROJECT_DIR/scripts/format-mermaid.py" "$SCHEMA_PATH" \
  --readme "$OUTPUT_DIR/README.md" \
  --tables-per-row "${TABLES_PER_DIAGRAM:-3}" \
  --ignore-tables "${IGNORE_TABLES:-flyway_schema_history}" \
  --show-descriptions "${SHOW_DESCRIPTIONS-enumValues,columnComments,notNull}" \
  --show-all-constraints "${SHOW_ALL_CONSTRAINTS:-true}"
echo "Markdown: $OUTPUT_DIR/README.md"

echo ""
echo "==> Done."
