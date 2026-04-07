# mermerd-flyway-github-action

A reusable GitHub Actions workflow that automatically generates [Mermaid-JS](https://mermaid-js.github.io/mermaid/#/entityRelationshipDiagram) ERD diagrams from a PostgreSQL database built via [Flyway](https://flywaydb.org/) migrations, using [mermerd](https://github.com/KarnerTh/mermerd).

## How it works

1. Detects changes in the configured migration path(s) by comparing against the previous commit
2. If changes are found, starts a **Docker Compose** project with PostgreSQL and Flyway
3. Flyway applies all migration scripts from the provided path(s)
4. **mermerd** generates an ERD diagram from the resulting database schema
5. The diagram is injected into the README between `<!-- mermerd-start -->` / `<!-- mermerd-end -->` markers
6. Changes are committed and pushed automatically

## Usage

### 1. Add markers to your README

In your client repository's README (or any markdown file), add the markers where the diagram should appear:

```markdown
## Database Schema

<!-- mermerd-start -->
<!-- mermerd-end -->
```

Any existing content between the markers will be replaced on each run.

### 2. Create a caller workflow

In your client repository, create `.github/workflows/update-erd.yml`:

```yaml
name: Update ERD Diagram

on:
  push:
    branches: [main]

jobs:
  update-erd:
    uses: <your-org>/mermerd-flyway-github-action/.github/workflows/mermerd.yml@main
    with:
      migration_paths: 'templates/docker/flyway/sql/init,templates/docker/flyway/sql/tables'
    permissions:
      contents: write
```

### 3. That's it

Whenever migration files change on push to `main`, the workflow will regenerate and commit the updated ERD diagram.

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `migration_paths` | **Yes** | | Comma-separated list of migration SQL directory paths relative to repo root |
| `readme_path` | No | `README.md` | Path to the markdown file containing the mermaid block markers |
| `db_name` | No | `mermerd_db` | PostgreSQL database name for the temporary database |
| `mermerd_version` | No | `0.13.0` | [mermerd release](https://github.com/KarnerTh/mermerd/releases) version |
| `show_all_constraints` | No | `true` | Show all constraints, even for non-selected tables |
| `show_descriptions` | No | `enumValues,columnComments,notNull` | Comma-separated descriptions to include |
| `ignore_tables` | No | `flyway_schema_history` | Comma-separated table patterns to ignore (supports regex) |
| `commit_message` | No | `chore: update mermerd ERD diagram` | Git commit message |
| `flyway_placeholder_prefix` | No | | Custom Flyway placeholder prefix (e.g. `{{ ` for Helm-style templates) |
| `flyway_placeholder_suffix` | No | | Custom Flyway placeholder suffix (e.g. ` }}` for Helm-style templates) |
| `flyway_placeholders` | No | | Comma-separated `key=value` placeholder pairs (e.g. `app_user=dummy,db_name=mydb`) |
| `force_generate` | No | `false` | Skip change detection and always generate the diagram |

## Full example

```yaml
name: Update ERD Diagram

on:
  push:
    branches: [main]
    paths:
      - 'db/migrations/**'

jobs:
  update-erd:
    uses: <your-org>/mermerd-flyway-github-action/.github/workflows/mermerd.yml@main
    with:
      migration_paths: 'db/migrations/init,db/migrations/tables'
      readme_path: 'docs/DATABASE.md'
      db_name: 'my_service_db'
      show_descriptions: 'enumValues,notNull'
      ignore_tables: 'flyway_schema_history,temp_.*'
      commit_message: 'docs: regenerate database ERD'
    permissions:
      contents: write
```

## Initial setup / bootstrap

The workflow only runs when migration files change in the triggering commit. When you first add the caller workflow to an existing repo, no migration files changed in that commit, so the diagram is never seeded.

Bootstrap it once with a `workflow_dispatch` job that passes `force_generate: true`:

```yaml
name: Update ERD Diagram

on:
  push:
    branches: [main]
  workflow_dispatch:
    inputs:
      force_generate:
        description: 'Force diagram regeneration even without migration changes'
        type: boolean
        default: false

jobs:
  update-erd:
    uses: <your-org>/mermerd-flyway-github-action/.github/workflows/mermerd.yml@main
    with:
      migration_paths: 'db/migrations'
      force_generate: ${{ github.event_name == 'workflow_dispatch' && inputs.force_generate }}
    permissions:
      contents: write
```

After merging, go to **Actions → Update ERD Diagram → Run workflow** and check **Force diagram regeneration**. Subsequent pushes will use normal change detection.

## Flyway placeholders

If your migration scripts use [Flyway placeholders](https://documentation.red-gate.com/fd/placeholders-configuration-184127475.html) with non-default delimiters, pass the prefix, suffix, and placeholder values:

```yaml
uses: <your-org>/mermerd-flyway-github-action/.github/workflows/mermerd.yml@main
with:
  migration_paths: 'db/migrations/init,db/migrations/tables'
  flyway_placeholder_prefix: '{{ '
  flyway_placeholder_suffix: ' }}'
  flyway_placeholders: 'app_user=dummy,app_password=dummy,db_name=mermerd_db'
```

The placeholder values are only used for the ephemeral migration — any value will work since the database is discarded after ERD generation.

## Local testing

A test script and dummy SQL migration are provided in the `test/` directory.

```bash
# Run the full pipeline (postgres + flyway + mermerd)
./test/run-test.sh

# Or step by step:
docker compose -f docker-compose.yml up -d postgres
docker compose -f docker-compose.yml run --rm flyway

# Cleanup
docker compose -f docker-compose.yml down -v
```

Defaults in [test/run-test.sh](test/run-test.sh) point to `test/sql`. Override any variable by exporting it before running, e.g.:

```bash
export WORKSPACE_PATH=/path/to/client-repo

# For migrations with placeholders:
export FLYWAY_PLACEHOLDER_PREFIX='{{ '
export FLYWAY_PLACEHOLDER_SUFFIX=' }}'
export FLYWAY_PLACEHOLDERS='app_user=dummy,app_password=dummy,db_name=mermerd_db'
```

## README marker format

The workflow locates the mermaid diagram block using HTML comment markers:

```markdown
<!-- mermerd-start -->
```mermaid
erDiagram
    ...
```
<!-- mermerd-end -->
```

Only one pair of markers per file is supported.
