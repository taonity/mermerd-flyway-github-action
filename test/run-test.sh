#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

MERMERD_VERSION="${MERMERD_VERSION:-0.13.0}"
MERMERD_CONFIG="$SCRIPT_DIR/mermerd.yaml"
MERMERD_BIN="$PROJECT_DIR/bin/mermerd"

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
docker compose -f "$PROJECT_DIR/docker-compose.yml" run --rm flyway

echo "==> Downloading mermerd v${MERMERD_VERSION}..."
if [ ! -x "$MERMERD_BIN" ]; then
  mkdir -p "$(dirname "$MERMERD_BIN")"
  curl -fsSL "https://github.com/KarnerTh/mermerd/releases/download/v${MERMERD_VERSION}/mermerd_${MERMERD_VERSION}_linux_amd64.tar.gz" \
    | tar xz -C "$(dirname "$MERMERD_BIN")" mermerd
  chmod +x "$MERMERD_BIN"
fi

echo "==> Running mermerd with $MERMERD_CONFIG..."
"$MERMERD_BIN" --runConfig "$MERMERD_CONFIG"

echo "==> Generated diagram:"
cat /tmp/mermerd-output.mmd

echo ""
echo "==> Done."
