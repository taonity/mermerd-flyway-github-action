import importlib.util
from pathlib import Path
import re
import tempfile
import unittest
from html import unescape
from html.parser import HTMLParser

SPEC = importlib.util.spec_from_file_location('erd', Path(__file__).parents[1] / 'scripts/format-mermaid.py')
erd = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(erd)

SOURCE = '''```mermaid
erDiagram
    parent {
        jsonb details "Example {object} & <tag>"
        uuid id PK "{NOT_NULL}"
        timestamp_without_time_zone created_at "{NOT_NULL}"
    }
    child {
        bytea payload
        uuid parent_id PK,FK "{NOT_NULL}"
        integer sequence PK "{NOT_NULL}"
    }
    child }o--|| parent : "parent_id"
```'''


class TableLabels(HTMLParser):
    def __init__(self):
        super().__init__()
        self.table = erd.Table('')
        self.cells, self.value, self.tag = [], '', None
        self.title = False

    def handle_starttag(self, tag, attrs):
        if tag in ('th', 'td'):
            self.tag, self.value = tag, ''
            self.title = tag == 'th' and dict(attrs).get('colspan') == '3'
        elif tag == 'tr':
            self.cells = []

    def handle_data(self, data):
        if self.tag:
            self.value += data

    def handle_endtag(self, tag):
        if tag == 'th' and self.title:
            self.table.name = self.value
        if tag == 'td':
            self.cells.append(self.value)
        if tag in ('td', 'th'):
            self.tag = None
        if tag == 'tr' and len(self.cells) == 3:
            name, kind, constraints = self.cells
            keys = tuple(re.findall(r'\b(?:PK|FK|UK)\b', constraints))
            self.table.columns.append(erd.Column(kind, name, keys, '', 'NOT NULL' in constraints or 'PK' in keys))


def diagrams(markdown):
    result = []
    for block in re.findall(r'```mermaid\n(.*?)```', markdown, re.S):
        tables = {}
        for key, markup in re.findall(r'(table_\d+)\["([^"]*)"\]', block):
            parser = TableLabels()
            parser.feed(markup)
            tables[key] = parser.table
        edges = []
        for left, arrow, value, right in re.findall(r'(table_\d+) (-->|-\.->)\|"([^"]*)"\| (table_\d+)', block):
            value = value.replace("<span class='schema-edge'>", '').replace('</span>', '')
            text, counts = unescape(value).split('<br/>')
            a, b = counts.split(' → ')
            lc = {'1': '||', '0..1': '|o', '0..*': '}o', '1..*': '}|'}
            rc = {'1': '||', '0..1': 'o|', '0..*': 'o{', '1..*': '|{'}
            edges.append(erd.Relation(tables[left].name, lc[a], '--' if arrow == '-->' else '..', rc[b], tables[right].name, text))
        result.append((list(tables.values()), edges))
    return result


def facts(tables):
    return {(t.name, c.name, erd.postgres_type(c.type), c.keys, bool(c.required)) for t in tables for c in t.columns}


class FormatterTest(unittest.TestCase):
    def test_semantics_constraints_and_literal_braces_are_preserved(self):
        tables, relations = erd.parse(SOURCE)
        output = erd.format_markdown(SOURCE)
        parsed = diagrams(output)
        formatted, _ = parsed[0]
        edges = [r for _, relations in parsed for r in relations]
        self.assertEqual(facts(tables), facts(formatted))
        self.assertEqual(relations, edges)
        self.assertIn('<td>id</td>', output)
        self.assertIn('Example {object} &amp; &lt;tag&gt;', output)
        self.assertNotIn('{NOT_NULL}', output)
        self.assertNotIn('<svg', output)
        self.assertNotIn('.svg', output)
        self.assertNotIn('<script', output)
        self.assertIn('flowchart TB', output)
        self.assertEqual(len(parsed), 1)
        self.assertIn('Column name', output)

    def test_primary_and_foreign_keys_come_before_ordinary_columns(self):
        tables, _ = diagrams(erd.format_markdown(SOURCE))[0]
        by_name = {t.name: t for t in tables}
        self.assertEqual(by_name['parent'].columns[0].name, 'id')
        self.assertEqual([c.name for c in by_name['child'].columns], ['parent_id', 'sequence', 'payload'])

    def test_large_connected_schema_keeps_every_table_and_relationship(self):
        source = 'erDiagram\n' + '\n'.join(f't{i} {{\n uuid id PK\n uuid parent_id FK\n}}' for i in range(17))
        source += '\n' + '\n'.join(f't{i} }}o--|| t{i + 1} : "parent_id"' for i in range(16))
        original, relations = erd.parse(source)
        for cap in (1, 2, 3):
            output = erd.format_markdown(source, cap)
            parsed = diagrams(output)
            self.assertEqual(len(parsed), 1)
            groups = re.findall(r'subgraph row_\d+\[" "\]\n(.*?)\nend', output, re.S)
            self.assertTrue(all(1 <= len(re.findall(r'table_\d+\[', group)) <= cap for group in groups))
            self.assertTrue(all(len(row) <= cap for row in erd.table_rows(original, relations, cap)))
            self.assertEqual(set().union(*(facts(tables) for tables, _ in parsed)), facts(original))
            self.assertCountEqual([r for _, edges in parsed for r in edges], relations)
            self.assertEqual(sum(len(t.columns) for tables, _ in parsed for t in tables), 34)

    def test_unrelated_tables_are_bounded_and_related_tables_stay_together(self):
        source = 'erDiagram\n' + '\n'.join(f't{i} {{\n uuid id PK\n}}' for i in range(10))
        source += '\nt3 }o--|| t4 : "id"'
        for cap in (1, 2, 3):
            parsed = diagrams(erd.format_markdown(source, cap))
            rows = erd.table_rows(*erd.parse(source), cap)
            self.assertTrue(all(len(row) <= cap for row in rows))
            if cap > 1:
                self.assertTrue(any({'t3', 't4'} <= {t.name for t in row} for row in rows))

    def test_starter_schema_is_one_name_first_mermaid_grid(self):
        source = (Path(__file__).parent / 'fixtures/starter.mmd').read_text(encoding='utf-8')
        parsed = diagrams(erd.format_markdown(source))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(len(parsed[0][0]), 5)
        self.assertEqual(sum(len(t.columns) for tables, _ in parsed for t in tables), 28)
        self.assertEqual(sum(len(edges) for _, edges in parsed), 1)

    def test_relationship_is_not_opposed_by_an_invisible_layout_edge(self):
        output = erd.format_markdown(SOURCE)
        real_pairs = {frozenset((a, b)) for a, b in re.findall(r'(table_\d+) (?:-->|-\.->)\|[^\n]+\| (table_\d+)', output)}
        layout_pairs = {frozenset((a, b)) for a, b in re.findall(r'(table_\d+) ~~~ (table_\d+)', output)}
        self.assertTrue(real_pairs)
        self.assertFalse(real_pairs & layout_pairs)

    def test_self_relations_and_dashed_cardinalities_are_preserved(self):
        source = 'erDiagram\n employee {\n uuid id PK\n }\n employee |o..o{ employee : "manager_id"'
        parsed = diagrams(erd.format_markdown(source))
        tables, _ = parsed[0]
        edges = [r for _, relations in parsed for r in relations]
        self.assertEqual(len(tables), 1)
        self.assertEqual((edges[0].left, edges[0].right, edges[0].left_card, edges[0].right_card), ('employee', 'employee', '|o', 'o{'))
        self.assertEqual(edges[0].line, '..')

    def test_quoted_and_schema_qualified_names_have_safe_styling_ids(self):
        source = 'erDiagram\n "public.user account" {\n uuid id PK\n }'
        output = erd.format_markdown(source)
        self.assertIn("<th colspan='3'>public.user account</th>", output)
        self.assertIn('class table_0 schemaNode', output)
        self.assertEqual(diagrams(output)[0][0][0].name, 'public.user account')

    def test_readme_update_is_idempotent_and_preserves_surroundings_and_crlf(self):
        for newline in ('\n', '\r\n'):
            with tempfile.TemporaryDirectory() as tmp:
                readme = Path(tmp) / 'README.md'
                readme.write_bytes(f'Before{newline}<!-- mermerd-start -->{newline}old{newline}<!-- mermerd-end -->{newline}After{newline}'.encode())
                erd.update_readme(SOURCE, readme)
                first = readme.read_bytes()
                self.assertTrue(first.startswith(f'Before{newline}<!-- mermerd-start -->'.encode()))
                self.assertTrue(first.endswith(f'<!-- mermerd-end -->{newline}After{newline}'.encode()))
                self.assertEqual(list(Path(tmp).iterdir()), [readme])
                erd.update_readme(SOURCE, readme)
                self.assertEqual(first, readme.read_bytes())

    def test_invalid_inputs_fail_before_readme_is_changed(self):
        for source in ('erDiagram', 'erDiagram\n x {\n uuid id', 'erDiagram\n x {\n bad attribute garbage\n }', SOURCE + '\n' + SOURCE):
            with self.assertRaises(ValueError):
                erd.parse(source)
        for cap in (0, 4):
            with self.assertRaises(ValueError):
                erd.format_markdown(SOURCE, cap)
        for original in ('<!-- mermerd-end -->\n<!-- mermerd-start -->', '<!-- mermerd-start -->', '<!-- mermerd-start --><!-- mermerd-start --><!-- mermerd-end -->'):
            with tempfile.TemporaryDirectory() as tmp:
                readme = Path(tmp) / 'README.md'
                readme.write_text(original)
                with self.assertRaises(ValueError):
                    erd.update_readme(SOURCE, readme)
                self.assertEqual(readme.read_text(), original)


if __name__ == '__main__':
    unittest.main()
