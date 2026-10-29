#!/usr/bin/env python3
"""Format tbls JSON or mermerd text as native Mermaid Markdown. No rendering."""

import argparse
from collections import deque
from dataclasses import dataclass, field
from html import escape
import json
from pathlib import Path
import re


@dataclass
class Column:
    type: str
    name: str
    keys: tuple = ()
    comment: str = ""
    required: bool | None = None


@dataclass
class Table:
    name: str
    columns: list = field(default_factory=list)


@dataclass
class Relation:
    left: str
    left_card: str
    line: str
    right_card: str
    right: str
    label: str


NAME = r'(?:"[^"\n]+"|[\w.-]+)'
RELATION = re.compile(
    rf'^({NAME})\s+([|o}}]{{2}})(--|\.\.)([|o{{]{{2}})\s+({NAME})\s*:\s*(.*)$'
)
ATTRIBUTE = re.compile(r'^(\S+)\s+(\S+)(?:\s+((?:PK|FK|UK)(?:\s*,\s*(?:PK|FK|UK))*))?(?:\s+"([^"]*)")?\s*$')
ALIASES = {
    "character_varying": "varchar", "character": "char",
    "timestamp_without_time_zone": "timestamp", "timestamp_with_time_zone": "timestamptz",
    "time_without_time_zone": "time", "time_with_time_zone": "timetz",
    "double_precision": "float8", "boolean": "bool", "integer": "int",
}


def postgres_type(kind):
    """Use equivalent short names while keeping lengths, precision, and arrays."""
    kind = re.sub(r'\s+', ' ', kind.strip())
    kind = re.sub(r'^character varying(?=\(|\[|$)', 'varchar', kind)
    kind = re.sub(r'^character(?=\(|\[|$)', 'char', kind)
    kind = re.sub(r'^(timestamp(?:\(\d+\))?) without time zone', r'\1', kind)
    kind = re.sub(r'^(timestamp(?:\(\d+\))?) with time zone', lambda m: m[1].replace('timestamp', 'timestamptz'), kind)
    kind = re.sub(r'^(time(?:\(\d+\))?) without time zone', r'\1', kind)
    kind = re.sub(r'^(time(?:\(\d+\))?) with time zone', lambda m: m[1].replace('time', 'timetz'), kind)
    kind = kind.replace(' ', '_')
    return ALIASES.get(kind, kind)


def parse_tbls(source, ignore_tables='flyway_schema_history', show_descriptions='enumValues,columnComments,notNull', show_all_constraints=True):
    data = json.loads(source)
    if not isinstance(data, dict) or not isinstance(data.get('tables'), list):
        raise ValueError('Expected a tbls JSON schema with a tables array')
    raw_tables = data['tables']
    patterns = [re.compile(p.strip()) for p in ignore_tables.split(',') if p.strip()]
    descriptions = {d.strip() for d in show_descriptions.split(',')}
    # Keep short labels for a single public schema; preserve qualification otherwise.
    public_only = bool(raw_tables) and all(t['name'].startswith('public.') for t in raw_tables)
    display = lambda name: name.removeprefix('public.') if public_only else name
    selected = {t['name']: t for t in raw_tables if not any(p.search(t['name']) or p.search(t['name'].split('.')[-1]) for p in patterns)}
    if not selected:
        raise ValueError('No tables remain after filtering the tbls schema')
    tables, primary_keys = {}, {}
    enums = {e['name']: e['values'] for e in data.get('enums', [])}
    for raw in raw_tables:
        primary_keys[raw['name']] = {name for c in raw.get('constraints', []) if c['type'] == 'PRIMARY KEY' for name in c.get('columns', [])}
    for name, raw in selected.items():
        keys = {c['name']: set() for c in raw['columns']}
        for constraint in raw.get('constraints', []):
            key = {'PRIMARY KEY': 'PK', 'FOREIGN KEY': 'FK', 'UNIQUE': 'UK'}.get(constraint['type'])
            if key:
                for column in constraint.get('columns', []):
                    if column not in keys:
                        raise ValueError(f'Unknown constrained column: {name}.{column}')
                    keys[column].add(key)
        # An unconditional, simple, single-column unique index is also a unique key.
        # Partial/expression/composite indexes must not imply individual uniqueness.
        for index in raw.get('indexes', []):
            definition = index.get('def', '')
            columns = index.get('columns', [])
            column_name = columns[0] if len(columns) == 1 else ''
            identifier = '(?:' + re.escape(column_name) + '|' + re.escape('"' + column_name.replace('"', '""') + '"') + ')'
            # Check the actual key expression too: some drivers list base columns
            # for expression indexes. PostgreSQL's pg_get_indexdef includes USING.
            simple_key = re.search(r'\bUSING\s+\w+\s*\(\s*' + identifier + r'\s*\)(?:\s+NULLS\s+(?:NOT\s+)?DISTINCT)?\s*$', definition, re.I)
            if (len(columns) == 1 and columns[0] in keys and re.match(r'^CREATE\s+UNIQUE\s+INDEX\b', definition, re.I)
                    and simple_key and 'PK' not in keys[columns[0]]):
                keys[columns[0]].add('UK')
        table = Table(display(name))
        for column in raw['columns']:
            if not isinstance(column.get('nullable'), bool):
                raise ValueError(f'Missing boolean nullability: {name}.{column["name"]}')
            comments = []
            if 'notNull' in descriptions and not column['nullable']:
                comments.append('NOT NULL')
            if 'columnComments' in descriptions and column.get('comment'):
                comments.append(column['comment'])
            enum_type = column['type'].removesuffix('[]')
            enum_name = enum_type if enum_type in enums else f'{name.rsplit(".", 1)[0]}.{enum_type}'
            if 'enumValues' in descriptions and enum_name in enums:
                comments.append('enum: ' + ', '.join(enums[enum_name]))
            comment = re.sub(r'\s+', ' ', ' · '.join(comments))
            table.columns.append(Column(postgres_type(column['type']), column['name'], tuple(k for k in ('PK', 'FK', 'UK') if k in keys[column['name']]), comment,
                                        not column['nullable'] if 'notNull' in descriptions else None))
        tables[name] = table
    left_cards = {'zero_or_more': '}o', 'one_or_more': '}|', 'exactly_one': '||', 'zero_or_one': '|o'}
    right_cards = {'zero_or_more': 'o{', 'one_or_more': '|{', 'exactly_one': '||', 'zero_or_one': 'o|'}
    relations = []
    for relation in data.get('relations', []):
        child, parent = relation['table'], relation['parent_table']
        if child not in selected and parent not in selected:
            continue
        if not show_all_constraints and (child not in selected or parent not in selected):
            continue
        try:
            left, right = left_cards[relation['cardinality']], right_cards[relation['parent_cardinality']]
        except KeyError as error:
            raise ValueError(f'Unsupported or missing tbls relationship cardinality: {relation}') from error
        for endpoint in (child, parent):
            tables.setdefault(endpoint, Table(display(endpoint)))
        identifying = bool(relation['columns']) and set(relation['columns']) <= primary_keys.get(child, set())
        relations.append(Relation(display(child), left, '--' if identifying else '..', right, display(parent), ', '.join(relation['columns'])))
    return list(tables.values()), relations


def parse(source, **options):
    source = source.lstrip('\ufeff')
    if source.lstrip().startswith('{'):
        return parse_tbls(source, **options)
    return parse_mermerd(source)


def parse_mermerd(source):
    """Accept mermerd's ER syntax; fail instead of silently dropping schema data."""
    blocks = re.findall(r'```mermaid\s*\n(.*?)```', source, re.S)
    if len(blocks) > 1:
        raise ValueError("Expected raw mermerd output with one diagram, not a formatted multi-diagram README")
    if blocks:
        source = blocks[0]
    tables, relations, current, aliases = {}, [], None, {}
    seen_header = False
    for number, raw in enumerate(source.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("%%"):
            continue
        if line == "erDiagram":
            seen_header = True
            continue
        if line.startswith("direction ") and current is None:
            continue
        if line.startswith("style ") and current is None:
            continue
        if current is not None:
            if line == "}":
                current = None
                continue
            match = ATTRIBUTE.fullmatch(line)
            if not match:
                raise ValueError(f"Unsupported attribute at line {number}: {line}")
            kind, name, keys, comment = match.groups()
            if any(c.name == name for c in current.columns):
                raise ValueError(f"Duplicate column {current.name}.{name}")
            # Other braces can be literal enum/comment text and must remain.
            required = True if '{NOT_NULL}' in (comment or '') or comment == 'NOT NULL' or 'PK' in (keys or '') else None
            current.columns.append(Column(kind, name, tuple(re.split(r'\s*,\s*', keys)) if keys else (), (comment or "").replace("{NOT_NULL}", "NOT NULL"), required))
            continue
        match = re.fullmatch(rf'({NAME})(?:\s*\["([^"\n]+)"\])?\s*\{{', line)
        if match:
            identifier = match[1].strip('"')
            name = match[2] or identifier
            aliases[identifier] = name
            if name in tables and tables[name].columns:
                raise ValueError(f"Duplicate table: {name}")
            current = tables.setdefault(name, Table(name))
            continue
        match = RELATION.fullmatch(line)
        if match:
            left, left_card, style, right_card, right, label = match.groups()
            left, right = left.strip('"'), right.strip('"')
            relations.append(Relation(left, left_card, style, right_card, right, label.strip('"')))
            continue
        raise ValueError(f"Unsupported Mermaid syntax at line {number}: {line}")
    for relation in relations:
        relation.left = aliases.get(relation.left, relation.left)
        relation.right = aliases.get(relation.right, relation.right)
        tables.setdefault(relation.left, Table(relation.left))
        tables.setdefault(relation.right, Table(relation.right))
    if not seen_header or not tables or current is not None:
        raise ValueError("Expected a non-empty erDiagram with closed table blocks")
    return list(tables.values()), relations


def components(tables, relations):
    by_name = {t.name: t for t in tables}
    neighbors = {name: set() for name in by_name}
    for relation in relations:
        neighbors[relation.left].add(relation.right)
        neighbors[relation.right].add(relation.left)
    unseen, groups = set(by_name), []
    for name in sorted(by_name):
        if name not in unseen:
            continue
        queue, group = deque([name]), []
        unseen.remove(name)
        while queue:
            name = queue.popleft()
            group.append(by_name[name])
            for neighbor in sorted(neighbors[name] & unseen):
                unseen.remove(neighbor)
                queue.append(neighbor)
        groups.append(group)
    return groups


TYPE_COLORS = {
    'Text': ('#dcf5ef', '#a6ddcf', '#0f766e'),
    'Number': ('#e1edff', '#b3ccf4', '#1d4ed8'),
    'DateTime': ('#eee5ff', '#d2b9f1', '#7e22ce'),
    'Boolean': ('#fff0cf', '#ecd18c', '#92400e'),
    'Binary': ('#fce5ef', '#efb7cf', '#be185d'),
    'Structured': ('#e8e7ff', '#c7c2f1', '#4338ca'),
    'Other': ('#e0f3fc', '#b3deee', '#14647e'),
}


def type_family(kind):
    kind = postgres_type(kind).lower()
    if kind.endswith('[]') or kind in ('json', 'jsonb', 'xml'):
        return 'Structured'
    if re.match(r'^(smallint|bigint|int\d*|numeric|decimal|real|float\d*|double|serial|bigserial|money)($|[(_])', kind):
        return 'Number'
    if kind.startswith(('timestamp', 'timestamptz', 'time(', 'timetz', 'interval')) or kind in ('date', 'time'):
        return 'DateTime'
    if kind in ('bool', 'boolean'):
        return 'Boolean'
    if kind.startswith(('bytea', 'binary', 'varbinary', 'blob', 'bit')):
        return 'Binary'
    if kind.startswith(('varchar', 'char', 'text', 'citext')) or kind == 'uuid':
        return 'Text'
    return 'Other'


def label(value):
    # Native Mermaid labels, including arbitrary quoted SQL identifiers.
    return escape(str(value), quote=True).replace('\n', '<br/>')


def table_rows(tables, relations, count):
    rows = []
    for component in components(tables, relations):
        if rows and len(rows[-1]) + len(component) <= count:
            rows[-1].extend(component)
        else:
            rows.extend(component[i:i + count] for i in range(0, len(component), count))
    return rows


def constraint_text(column):
    keys = ', '.join(column.keys)
    return ' · '.join(p for p in (keys, 'NOT NULL' if column.required and 'PK' not in column.keys else '') if p) or '—'


CARDINALITIES = {'||': '1', '|o': '0..1', 'o|': '0..1', '}o': '0..*', 'o{': '0..*', '}|': '1..*', '|{': '1..*'}


def relationship_label(relation):
    return relation.label + '\n' + CARDINALITIES[relation.left_card] + ' → ' + CARDINALITIES[relation.right_card]


DARK_TYPE_COLORS = {
    'Text': ('#173d38', '#467267', '#a7dfd2'),
    'Number': ('#1f3557', '#4c6b9b', '#b6ceff'),
    'DateTime': ('#382a50', '#72568f', '#d9baf3'),
    'Boolean': ('#44361e', '#89713f', '#f2d08c'),
    'Binary': ('#482637', '#8f536e', '#f0bad0'),
    'Structured': ('#2c2b50', '#615e95', '#c6c3fa'),
    'Other': ('#223c49', '#4c798e', '#b0ddeb'),
}


def css_rgb(value):
    # Hex + semicolon is interpreted as an entity inside some Mermaid labels.
    return 'rgb(' + ' '.join(str(int(value[i:i + 2], 16)) for i in (1, 3, 5)) + ')'


def adaptive_color(light, dark):
    return f'light-dark({css_rgb(light)},{css_rgb(dark)})'


def palette_css(prefix):
    rules = []
    for family, (fill, _, foreground) in TYPE_COLORS.items():
        dark_fill, _, dark_foreground = DARK_TYPE_COLORS[family]
        rules.append(f'{prefix}.type{family}' + '{background-color:' + adaptive_color(fill, dark_fill)
                     + ';color:' + adaptive_color(foreground, dark_foreground) + ';}')
    return ''.join(rules)


SCHEME_CSS = (
    # The viewers can paint a dark background without declaring color-scheme.
    '.schema-table,.schema-edge{color-scheme:light dark;}'
    # @scope keeps host selectors outside Mermaid's diagram-ID CSS prefix.
    '@scope ([data-color-mode=dark],.vscode-dark,.vscode-high-contrast,[data-theme=dark])'
    '{.schema-table,.schema-edge{color-scheme:dark;}}'
    '@scope ([data-color-mode=light],.vscode-light,.vscode-high-contrast-light,[data-theme=light])'
    '{.schema-table,.schema-edge{color-scheme:light;}}'
)


SCHEMA_CSS = (
    '.schema-table{border-collapse:collapse;white-space:nowrap;font:12px/1.3 Verdana,sans-serif;'
    'color:' + adaptive_color('#20344d', '#dce5f1') + ';background-color:' + adaptive_color('#ffffff', '#18202b')
    + ';border:1px solid ' + adaptive_color('#bcc9d8', '#526174') + ';}'
    '.schema-table th,.schema-table td{font:12px/1.3 Verdana,sans-serif;}'
    '.schema-table th{padding:3px 6px;text-align:center;font-weight:600;background-color:'
    + adaptive_color('#e8eef5', '#2a3544') + ';}'
    '.schema-table td{padding:2px 6px;text-align:left;border-top:1px solid '
    + adaptive_color('#e5ebf2', '#344153') + ';}'
    + palette_css('.schema-table ')
    + '.schema-table .primaryKey{background-color:' + adaptive_color(TYPE_COLORS['Boolean'][0], DARK_TYPE_COLORS['Boolean'][0])
    + ';color:' + adaptive_color(TYPE_COLORS['Boolean'][2], DARK_TYPE_COLORS['Boolean'][2]) + ';}'
    '.schema-table .foreignKey{background-color:' + adaptive_color(TYPE_COLORS['Number'][0], DARK_TYPE_COLORS['Number'][0])
    + ';color:' + adaptive_color(TYPE_COLORS['Number'][2], DARK_TYPE_COLORS['Number'][2]) + ';}'
    '.schema-table .uniqueKey{background-color:' + adaptive_color(TYPE_COLORS['DateTime'][0], DARK_TYPE_COLORS['DateTime'][0])
    + ';color:' + adaptive_color(TYPE_COLORS['DateTime'][2], DARK_TYPE_COLORS['DateTime'][2]) + ';}'
    '.schema-edge{display:inline-block;padding:2px 4px;text-align:left;font:12px/1.3 Verdana,sans-serif;'
    'color:' + adaptive_color('#20344d', '#dce5f1') + ';background:' + adaptive_color('#e8eef5', '#2a3544') + ';}'
    + SCHEME_CSS
)


def table_label(table):
    rows = [f"<table class='schema-table'><thead><tr><th colspan='3'>{escape(table.name)}</th></tr>"
            '<tr><th>Column name</th><th>Data type</th><th>Constraints</th></tr></thead><tbody>']
    ordered = sorted(table.columns, key=lambda c: 0 if 'PK' in c.keys else 1 if 'FK' in c.keys else 2)
    for column in ordered:
        key_class = 'primaryKey' if 'PK' in column.keys else 'foreignKey' if 'FK' in column.keys else 'uniqueKey' if 'UK' in column.keys else 'plainConstraint'
        rows.append(f"<tr><td>{escape(column.name)}</td><td class='type{type_family(column.type)}'>{escape(postgres_type(column.type))}</td>"
                    f"<td class='{key_class}'>{escape(constraint_text(column))}</td></tr>")
    rows.append('</tbody></table>')
    # Only label text can contain double quotes; escape those for the Mermaid string.
    return ''.join(rows).replace('"', '&quot;')


def diagram(tables, relations, tables_per_row=3):
    identifiers = {name: f'table_{i}' for i, name in enumerate(sorted(t.name for t in tables))}
    rows = table_rows(tables, relations, tables_per_row)
    related_pairs = {frozenset((r.left, r.right)) for r in relations}
    config = {
        'theme': 'base', 'look': 'classic', 'htmlLabels': True, 'fontFamily': 'Verdana, sans-serif', 'layout': 'dagre',
        'themeVariables': {'fontSize': '12px', 'primaryColor': '#ffffff', 'primaryBorderColor': '#bcc9d8',
                          'primaryTextColor': '#20344d', 'lineColor': '#7196bd', 'edgeLabelBackground': 'transparent'},
        'themeCSS': SCHEMA_CSS,
        # Mermaid 11 treats zero as unset and substitutes 8px, separating arrow
        # endpoints from the visible HTML table. A subpixel value avoids that.
        'flowchart': {'padding': 0.01, 'wrappingWidth': 100000, 'rankSpacing': 24, 'nodeSpacing': 18,
                      'curve': 'linear', 'subGraphTitleMargin': {'top': 0, 'bottom': 0}},
    }
    lines = ['```mermaid', '%%{init: ' + json.dumps(config, separators=(',', ':')) + '}%%',
             'flowchart TB']
    for index, group in enumerate(rows):
        lines.extend([f'subgraph row_{index}[" "]', 'direction LR'])
        lines.extend(f'{identifiers[t.name]}["{table_label(t)}"]' for t in group)
        # Invisible links guide layout only; visible arrows are database FKs.
        # A real FK already arranges these neighbors. A second, opposite layout
        # edge creates a cycle and makes Dagre bend the FK away from the centers.
        lines.extend(f'{identifiers[a.name]} ~~~ {identifiers[b.name]}' for a, b in zip(group, group[1:])
                     if frozenset((a.name, b.name)) not in related_pairs)
        lines.extend(['end', f'style row_{index} fill:transparent,stroke:transparent'])
        if index:
            lines.append(f'row_{index - 1} ~~~ row_{index}')
    for relation in relations:
        arrow = '-->' if relation.line == '--' else '-.->'
        lines.append(f'{identifiers[relation.left]} {arrow}|"<span class=\'schema-edge\'>{label(relationship_label(relation))}</span>"| {identifiers[relation.right]}')
    lines.append('classDef schemaNode fill:transparent,stroke:transparent')
    lines.append('class ' + ','.join(identifiers.values()) + ' schemaNode')
    return '\n'.join(lines + ['```'])


def format_markdown(source, tables_per_diagram=3, **options):
    if tables_per_diagram not in (1, 2, 3):
        raise ValueError('tables_per_diagram must be 1, 2, or 3')
    tables, relations = parse(source, **options)
    parts = [diagram(tables, relations, tables_per_diagram)]
    notes = []
    for table in tables:
        for column in table.columns:
            comment = column.comment
            if column.required and comment.startswith('NOT NULL'):
                comment = comment[len('NOT NULL'):].lstrip(' ·')
            if comment:
                # Comments stay outside the grid so they cannot make tables wider.
                notes.append(f'- **{escape(table.name)}.{escape(column.name)}:** {escape(comment)}')
    if notes:
        parts.append('**Column notes**\n\n' + '\n'.join(notes))
    return '\n\n'.join(parts) + '\n'


def update_readme(source, readme, tables_per_diagram=3, **options):
    # Preserve the caller's newline convention and all text outside the markers.
    body = readme.read_bytes().decode('utf-8')
    start, end = '<!-- mermerd-start -->', '<!-- mermerd-end -->'
    if body.count(start) != 1 or body.count(end) != 1 or body.index(start) >= body.index(end):
        raise ValueError("README must contain exactly one ordered pair of mermerd markers")
    formatted = format_markdown(source, tables_per_diagram, **options)
    newline = '\r\n' if '\r\n' in body else '\n'
    replacement = newline + formatted.replace('\n', newline)
    updated = body[:body.index(start) + len(start)] + replacement + body[body.index(end):]
    readme.write_bytes(updated.encode('utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--readme', type=Path, required=True)
    parser.add_argument('--tables-per-row', '--tables-per-diagram', dest='tables_per_diagram', type=int, choices=(1, 2, 3), default=3)
    parser.add_argument('--ignore-tables', default='flyway_schema_history', help='Comma-separated regex patterns, matched against full and short names in tbls JSON')
    parser.add_argument('--show-descriptions', default='enumValues,columnComments,notNull')
    parser.add_argument('--show-all-constraints', choices=('true', 'false'), default='true')
    args = parser.parse_args()
    try:
        update_readme(args.source.read_text(encoding='utf-8'), args.readme, args.tables_per_diagram,
                      ignore_tables=args.ignore_tables, show_descriptions=args.show_descriptions,
                      show_all_constraints=args.show_all_constraints == 'true')
    except (ValueError, OSError, KeyError, TypeError, re.error) as error:
        parser.exit(1, f'Mermaid formatting failed: {error}\n')
    print(f'Updated {args.readme} (Mermaid Markdown, at most {args.tables_per_diagram} tables per row)')


if __name__ == '__main__':
    main()
