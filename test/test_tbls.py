import copy
import json
from pathlib import Path
import tempfile
import unittest

from test_format_mermaid import erd, diagrams


FIXTURE = Path(__file__).parent / 'fixtures/starter.tbls.json'


def column(name, kind='integer', nullable=False, **extra):
    return {'name': name, 'type': kind, 'nullable': nullable, **extra}


def schema():
    return {
        'tables': [
            {'name': 'public.parent', 'columns': [column('id')],
             'constraints': [{'type': 'PRIMARY KEY', 'columns': ['id']}]},
            {'name': 'public.child', 'columns': [column('id'), column('parent_id', nullable=True), column('sequence')],
             'constraints': [{'type': 'PRIMARY KEY', 'columns': ['id']}, {'type': 'FOREIGN KEY', 'columns': ['parent_id'], 'referenced_table': 'public.parent'}]},
        ],
        'relations': [{'table': 'public.child', 'columns': ['parent_id'], 'cardinality': 'zero_or_more',
                       'parent_table': 'public.parent', 'parent_columns': ['id'], 'parent_cardinality': 'zero_or_one'}],
    }


class TblsTest(unittest.TestCase):
    def test_real_postgres_export_preserves_keys_nullability_and_type_lengths(self):
        tables, relations = erd.parse(FIXTURE.read_text())
        self.assertEqual(len(tables), 5)
        self.assertEqual(sum(len(t.columns) for t in tables), 28)
        self.assertEqual(len(relations), 1)
        by_name = {t.name: {c.name: c for c in t.columns} for t in tables}
        self.assertEqual(by_name['app_user']['google_id'].keys, ('PK',))
        self.assertEqual(by_name['spring_session']['session_id'].keys, ('UK',))
        self.assertEqual(by_name['spring_session_attributes']['session_primary_id'].keys, ('PK', 'FK'))
        self.assertEqual(by_name['spring_session_attributes']['attribute_name'].keys, ('PK',))
        self.assertEqual(by_name['config_override']['value_json'].type, 'varchar(20000)')
        self.assertEqual(by_name['spring_session']['principal_name'].comment, '')
        self.assertEqual(by_name['spring_session']['session_id'].comment, 'NOT NULL')
        self.assertEqual(relations[0].line, '--')  # FK is part of the composite PK.
        self.assertEqual(len(diagrams(erd.format_markdown(FIXTURE.read_text()))[0][0]), 5)

    def test_optional_relationship_cardinality_comes_from_tbls_metadata(self):
        data = schema()
        tables, edges = erd.parse(json.dumps(data))
        self.assertEqual(edges[0].right_card, 'o|')
        self.assertEqual(edges[0].left_card, '}o')
        self.assertEqual(edges[0].line, '..')
        data['relations'][0]['cardinality'] = 'zero_or_one'
        self.assertEqual(erd.parse(json.dumps(data))[1][0].left_card, '|o')

    def test_partial_expression_and_composite_indexes_do_not_imply_single_column_uniqueness(self):
        data = schema()
        child = data['tables'][1]
        for definition, columns in [
            ('CREATE UNIQUE INDEX ix ON child USING btree (parent_id) WHERE parent_id > 0', ['parent_id']),
            ('CREATE UNIQUE INDEX ix ON child USING btree (parent_id, sequence)', ['parent_id', 'sequence']),
            ('CREATE UNIQUE INDEX ix ON child USING btree ((sequence + 1))', ['sequence']),
            ('CREATE INDEX ix ON child USING btree (parent_id)', ['parent_id']),
        ]:
            child['indexes'] = [{'def': definition, 'columns': columns}]
            tables, _ = erd.parse(json.dumps(data))
            self.assertFalse(any('UK' in c.keys for t in tables for c in t.columns))
        child['indexes'] = [{'def': 'CREATE UNIQUE INDEX ix ON child USING btree (parent_id)', 'columns': ['parent_id']}]
        self.assertIn('UK', erd.parse(json.dumps(data))[0][1].columns[1].keys)

    def test_filters_control_referenced_table_context_without_losing_local_foreign_key(self):
        source = json.dumps(schema())
        tables, edges = erd.parse(source, ignore_tables='^parent$', show_all_constraints=True)
        self.assertEqual({t.name: len(t.columns) for t in tables}, {'child': 3, 'parent': 0})
        self.assertEqual(len(edges), 1)
        tables, edges = erd.parse(source, ignore_tables='^parent$', show_all_constraints=False)
        self.assertEqual([t.name for t in tables], ['child'])
        self.assertEqual(edges, [])
        self.assertEqual(tables[0].columns[1].keys, ('FK',))
        with self.assertRaisesRegex(ValueError, 'No tables remain'):
            erd.parse(source, ignore_tables='.*')

    def test_descriptions_enums_and_comments_are_safe_mermaid_text(self):
        data = schema()
        data['tables'][0]['columns'][0].update(type='status', comment='State "ready"\nwith {braces}')
        data['enums'] = [{'name': 'public.status', 'values': ['ready', 'done']}]
        source = json.dumps(data)
        tables, _ = erd.parse(source)
        comment = tables[0].columns[0].comment
        self.assertIn('NOT NULL', comment)
        self.assertIn('"ready"', comment)
        self.assertIn('{braces}', comment)
        self.assertIn('enum: ready, done', comment)
        self.assertNotIn('\n', comment)
        self.assertEqual(erd.parse(source, show_descriptions='')[0][0].columns[0].comment, '')

    def test_multiple_schemas_do_not_collapse_tables_with_identical_names(self):
        data = schema()
        extra = copy.deepcopy(data['tables'][0])
        extra['name'] = 'sales.parent'
        data['tables'].append(extra)
        tables, edges = erd.parse(json.dumps(data))
        self.assertEqual({t.name for t in tables}, {'public.parent', 'public.child', 'sales.parent'})
        self.assertEqual(edges[0].right, 'public.parent')

    def test_nullable_column_comment_does_not_become_a_constraint(self):
        data = schema()
        data['tables'][1]['columns'][1]['comment'] = 'Will be NOT NULL later'
        tables, _ = erd.parse(json.dumps(data))
        child = next(t for t in tables if t.name == 'child')
        parent_id = next(c for c in child.columns if c.name == 'parent_id')
        self.assertEqual(erd.constraint_text(parent_id), 'FK')

    def test_type_families_are_consistent_across_declared_lengths(self):
        for kind, family in [('varchar(20)', 'Text'), ('varchar(20000)', 'Text'),
                             ('bigint', 'Number'), ('numeric(12,2)', 'Number'),
                             ('timestamptz(3)', 'DateTime'), ('date', 'DateTime'),
                             ('boolean', 'Boolean'), ('bytea', 'Binary'),
                             ('jsonb', 'Structured'), ('varchar(20)[]', 'Structured')]:
            self.assertEqual(erd.type_family(kind), family)

    def test_sql_types_preserve_precision_arrays_and_timezone_meaning(self):
        for original, expected in [
            ('character varying(40)', 'varchar(40)'), ('character(36)', 'char(36)'),
            ('numeric(12,2)', 'numeric(12,2)'), ('timestamp(3) with time zone', 'timestamptz(3)'),
            ('time(2) without time zone', 'time(2)'), ('double precision', 'float8'),
            ('varchar(20)[]', 'varchar(20)[]'),
        ]:
            self.assertEqual(erd.postgres_type(original), expected)

    def test_numeric_precision_is_in_the_type_cell_with_names_first(self):
        data = schema()
        data['tables'][0]['columns'][0]['type'] = 'numeric(12,2)'
        output = erd.format_markdown(json.dumps(data))
        self.assertIn('>numeric(12,2)</td>', output)
        table = next(t for t in diagrams(output)[0][0] if t.name == 'parent')
        self.assertEqual(table.columns[0].name, 'id')
        self.assertEqual(table.columns[0].type, 'numeric(12,2)')

    def test_malformed_tbls_metadata_fails_before_readme_is_changed(self):
        missing_nullable, bad_cardinality = schema(), schema()
        del missing_nullable['tables'][0]['columns'][0]['nullable']
        bad_cardinality['relations'][0]['cardinality'] = 'unknown'
        for data in ({'tables': 'bad'}, missing_nullable, bad_cardinality):
            with tempfile.TemporaryDirectory() as tmp:
                readme = Path(tmp) / 'README.md'
                original = '<!-- mermerd-start -->\nold\n<!-- mermerd-end -->'
                readme.write_text(original)
                with self.assertRaises(ValueError):
                    erd.update_readme(json.dumps(data), readme)
                self.assertEqual(readme.read_text(), original)

    def test_primary_keys_do_not_repeat_not_null_but_other_required_keys_do(self):
        for keys, expected in [(('PK',), 'PK'), (('PK', 'FK'), 'PK, FK'),
                               (('FK',), 'FK · NOT NULL'), (('UK',), 'UK · NOT NULL'),
                               ((), 'NOT NULL')]:
            field = erd.Column('uuid', 'id', keys, required=True)
            self.assertEqual(erd.constraint_text(field), expected)


if __name__ == '__main__':
    unittest.main()
