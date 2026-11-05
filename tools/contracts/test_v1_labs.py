"""Executable linkage for docs/labs/: every failure-matrix row must appear in
exactly one lab document, and every lab must reference real lesson CLIs."""
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
LABS = ROOT / 'docs/labs'
MATRIX = ROOT / 'fixtures/failure-matrix.yaml'


def lab_documents():
    return {path.name: path.read_text(encoding='utf-8')
            for path in sorted(LABS.glob('lab-*.md'))}


def matrix_rows():
    document = yaml.safe_load(MATRIX.read_text(encoding='utf-8'))
    return {row['failure_id']: row for row in document['rows']}


class V1LabsTests(unittest.TestCase):
    def test_every_matrix_row_appears_in_exactly_one_lab(self):
        labs = lab_documents()
        for failure_id in matrix_rows():
            hits = [name for name, text in labs.items()
                    if re.search(rf'`{failure_id}`', text)]
            self.assertEqual(len(hits), 1,
                             f'{failure_id} must appear in exactly one lab, found {hits}')

    def test_lab_count_matches_lesson_count(self):
        labs = lab_documents()
        self.assertEqual(len(labs), 6, 'one lab per lesson M0-M5')

    def test_labs_are_indexed(self):
        index = (LABS / 'README.md').read_text(encoding='utf-8')
        for name in lab_documents():
            self.assertIn(name, index, f'{name} must be linked from the lab index')

    def test_exercise_commands_reference_real_lesson_grammars(self):
        labs = lab_documents()
        text = ''.join(labs.values())
        self.assertIn('npx tsx src/cli.ts', text)
        self.assertIn('python tools/inspector.py', text)
        self.assertNotIn('--prefix lessons', text)

    def test_expected_responses_come_from_the_matrix(self):
        rows = matrix_rows()
        labs = lab_documents()
        text = ''.join(labs.values())
        for failure_id, row in rows.items():
            code = row['expected_response'].get('failure_code')
            if code:
                self.assertIn(code, text,
                              f'{failure_id} failure code {code} must appear in a lab')


if __name__ == '__main__':
    unittest.main()
