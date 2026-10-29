# mermerd-flyway-github-action

A reusable GitHub Actions workflow that generates name-first Mermaid Markdown database diagrams from PostgreSQL schemas built via [Flyway](https://flywaydb.org/) migrations. [tbls](https://github.com/k1LoW/tbls) exports structured schema metadata; a small formatter puts every table and foreign-key arrow in one native Mermaid diagram. No image files or custom renderer are used.

The workflow filename and README markers retain their original names so existing callers keep working. Set `schema_generator: mermerd` to use the legacy [mermerd](https://github.com/KarnerTh/mermerd) extractor instead.

See the [generated Mermaid example](docs/example-schema.md).

## Diagram design

- **Vertical growth:** row groups hold up to one, two, or three tables. The default is three. Connected tables stay together when they fit; additional tables create new rows. Cross-row relationships may make Mermaid stack a group vertically to route its arrows.
- **Names first:** every table has **Column name → Data type → Constraints** headings. There is no swapped name/type data or extra column-count label.
- **Type colors:** text cells are teal, numbers blue, dates/times purple, booleans amber, binary pink, and structured data indigo. The same type family uses the same color throughout the schema. All table titles and column headers share one neutral style.
- **Clear constraints:** `PK`, `FK`, `UK`, and plain `NOT NULL` labels. Mermerd's `{NOT_NULL}` wrapper is removed. Other braces in actual comments and enum values are preserved in the notes below the grid.
- **Compact and aligned:** columns fit their contents, body text is left-aligned, headers are centered, and 12px text uses tight cell padding. Primary and foreign key rows appear first. PK implies NOT NULL, so primary-key cells show only `PK` or `PK, FK`; other required fields retain `NOT NULL`. Declared lengths, precision, arrays, and timezone distinctions remain in type cells. Long comments and enum values stay below the grid.
- **Light and dark:** one Markdown artifact adapts cell backgrounds, text, headers, and relationship labels to the surrounding page's color scheme using CSS `light-dark()`. The preview provides System, Light, and Dark choices. Type and constraint colors remain readable in both palettes.
- **Readable relationships:** arrows connect the full tables directly in the same diagram, with FK column names and endpoint counts (`0..* → 1`, for example). Full column definitions appear once. Solid lines represent identifying relationships; dashed lines represent other relationships.

## tbls trial

The Fullstack Starter schema produces **five tables, 28 columns, and one foreign-key relationship**, matching the existing mermerd extraction. The tbls JSON path also preserves declared lengths such as `varchar(20000)` and marks `spring_session.session_id` as `UK` from its unique index.

tbls's direct Mermaid export in this trial omits primary-key and `NOT NULL` labels. We use its JSON output to retain those fields, composite keys, comments, enum values, and relationship cardinalities. Primary/foreign/unique constraints are mapped to Mermaid keys; unconditional simple single-column unique indexes also produce `UK`. Partial, expression, or composite indexes do not imply that each individual column is unique.

## Diagram format

The output uses one [Mermaid flowchart](https://mermaid.js.org/syntax/flowchart.html) (`flowchart TB`) for all tables and relationships. Transparent row subgraphs and invisible layout links guide vertical growth; visible arrows represent database foreign keys. Each table is a compact Mermaid HTML label, styled by the diagram's `themeCSS`. Content-sized columns and left alignment are defined inside the Mermaid Markdown, with no custom SVG processing or renderer. Mermaid JS renders it; Python only formats text.

`tables_per_diagram` is the existing workflow input name; it now controls tables per **row** and accepts `1`, `2`, or `3`. The CLI uses `--tables-per-row` and retains `--tables-per-diagram` as an alias. Long identifiers can widen individual cells, but cannot add a fourth table to a row.

Only relationships emitted by the selected extractor are drawn. Invisible `~~~` links position rows and tables; they are layout instructions, not schema relationships. Cardinalities are written explicitly on arrows. Full index definitions, defaults, and check constraints remain in the intermediate JSON. The legacy mermerd path cannot recover metadata its text export omits.

Input must be tbls JSON or raw single-diagram mermerd ER text. Unrecognized metadata/syntax fails explicitly; an already formatted README is not valid input. `—` means no displayed constraint, not an assertion of nullability, since `notNull` descriptions can be disabled.

GitHub controls its Mermaid version and rendering environment; see [GitHub's diagram documentation](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/creating-diagrams) for checking the active version with an `info` diagram. The local preview checks actual Mermaid JS, but is not a verification of GitHub's hosted renderer.

## How it works

1. Detects changes in the configured migration path(s) by comparing against the previous commit
2. If changes are found, starts a **Docker Compose** project with PostgreSQL and Flyway
3. Flyway applies all migration scripts from the provided path(s)
4. **tbls** exports the resulting `public` schema as JSON (or **mermerd** exports Mermaid text when selected)
5. A dependency-free Python formatter maps schema metadata and emits a name-first native Mermaid grid
6. The README between `<!-- mermerd-start -->` / `<!-- mermerd-end -->` is updated
7. The README is committed and pushed automatically

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
      schema_generator: tbls
      tables_per_diagram: 3
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
| `tables_per_diagram` | No | `3` | Tables per row in the Mermaid grid: `1`, `2`, or `3` |
| `db_name` | No | `mermerd_db` | PostgreSQL database name for the temporary database |
| `schema_generator` | No | `tbls` | `tbls` for structured JSON extraction; `mermerd` for the legacy Mermaid text path |
| `tbls_version` | No | `1.96.1` | [tbls release](https://github.com/k1LoW/tbls/releases) version |
| `mermerd_version` | No | `0.13.0` | [mermerd release](https://github.com/KarnerTh/mermerd/releases) version; used only with `schema_generator: mermerd` |
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

Python 3.10+ is required for formatting. GitHub's Ubuntu runner includes it. No Python packages need installing.

Run the design demo using the bundled Fullstack Starter schema (no database required):

```bash
python test/preview.py
```

The default fixture is a tbls JSON export of the Fullstack Starter schema. This opens `http://127.0.0.1:8765/preview.html`. The local viewer renders the actual Markdown with Mermaid JS 11.12.2 from jsDelivr; it needs internet access. Its selectors switch between one, two, and three tables per row and System/Light/Dark themes. Download Markdown saves the selected layout; its colors remain theme-adaptive. Use `?theme=light` or `?theme=dark` for a theme-specific preview link. The temporary viewer is not published by the workflow. Use `--source path/to/schema.json` (or legacy `.mmd`) to preview another schema, `--tables-per-row 1` to choose the initial layout, `--port` to change the port, or `--no-open` to skip opening a browser. `--mermaid-url` can point to a locally served Mermaid ESM bundle for offline testing. Press Ctrl+C to stop.

Run the formatter tests on Windows, Linux, or macOS:

```bash
python -m unittest discover -s test -p 'test_*.py' -v
```

Export with tbls and format its JSON (the README must already have its markers):

```bash
tbls out 'postgres://user:password@localhost:5432/mydb?sslmode=disable' --include 'public.*' --format json --out schema.json
python scripts/format-mermaid.py schema.json --readme README.md --tables-per-row 3
```

The formatter auto-detects tbls JSON or legacy mermerd text. The Bash wrapper `scripts/update-readme.sh README.md schema.json` accepts the same flags. `--ignore-tables` takes comma-separated regex patterns matched against full and short table names in JSON. `--show-descriptions` accepts `enumValues,columnComments,notNull`; use an empty value to hide descriptions. With `--show-all-constraints false`, references to excluded tables are hidden; otherwise those tables appear as name-only context. The legacy extractor applies those filtering options upstream. Formatting changes only the target Markdown file; it creates no image or HTML artifacts.

A test script and dummy SQL migration are provided in the `test/` directory for the complete database pipeline. Run it in Bash (WSL works on Windows):

```bash
# Run the full pipeline (postgres + flyway + tbls JSON + Mermaid Markdown)
./test/run-test.sh

# Compare the legacy extractor
SCHEMA_GENERATOR=mermerd ./test/run-test.sh

# Or step by step:
docker compose -f docker-compose.yml up -d postgres
docker compose -f docker-compose.yml run --rm flyway

# Cleanup
docker compose -f docker-compose.yml down -v
```

Defaults in [test/run-test.sh](test/run-test.sh) point to `test/sql`. Override any variable by exporting it before running, e.g.:

```bash
export WORKSPACE_PATH=/path/to/client-repo
export OUTPUT_DIR=/path/to/diagram-output
export TABLES_PER_DIAGRAM=3
export SCHEMA_GENERATOR=tbls

# For migrations with placeholders:
export FLYWAY_PLACEHOLDER_PREFIX='{{ '
export FLYWAY_PLACEHOLDER_SUFFIX=' }}'
export FLYWAY_PLACEHOLDERS='app_user=dummy,app_password=dummy,db_name=mermerd_db'
```

## README marker format

The workflow locates the generated diagram section using HTML comment markers. The resulting section contains one Mermaid fence, for example:

````markdown
<!-- mermerd-start -->
```mermaid
flowchart TB
    table_0["<table><tr><th colspan='3'>app_user</th></tr><tr><th>Column name</th><th>Data type</th><th>Constraints</th></tr><tr><td align='left'>google_id</td><td align='left'>varchar</td><td align='left'>PK</td></tr></table>"]
```
<!-- mermerd-end -->
````

Exactly one ordered pair of markers per file is required. To adopt the new design in an existing caller, merge these changes into the action repository and run the caller once with `force_generate: true`; normal migration-change detection applies afterward.
