"""Executable linkage for docs/production-checklist.md: every checklist row's
gate must exist and every referenced invariant/matrix identifier must resolve.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKLIST = ROOT / 'docs/production-checklist.md'
INVARIANT_FILES = {
    0: 'lessons/00-workflow-or-agent/invariants.yaml',
    1: 'lessons/01-bounded-tool-loop/invariants.yaml',
    2: 'lessons/02-routing-handoff/invariants.yaml',
    3: 'lessons/03-parallel-fanout-fanin/invariants.yaml',
    4: 'lessons/04-durable-state-recovery/invariants.yaml',
    5: 'lessons/05-side-effects-approval/invariants.yaml',
}
ROW = re.compile(r'^\| (V1-[SEORVCP][0-9]+) \| (.+?) \| (scripts/verify_m\d\.py) \| (.+?) \|$', re.M)


def checklist_rows():
    text = CHECKLIST.read_text(encoding='utf-8')
    rows = ROW.findall(text)
    assert rows, 'checklist rows must use the fixed five-column format'
    return rows


def invariant_ids():
    import yaml
    ids = set()
    for lesson, relative in INVARIANT_FILES.items():
        catalog = yaml.safe_load((ROOT / relative).read_text(encoding='utf-8'))
        for entry in catalog['invariants']:
            ids.add(entry['id'])
    return ids


def matrix_row_ids():
    import yaml
    document = yaml.safe_load((ROOT / 'fixtures/failure-matrix.yaml').read_text(encoding='utf-8'))
    return {row['failure_id'] for row in document['rows']}


class V1ChecklistTests(unittest.TestCase):
    def test_rows_parse_and_cover_the_seven_sections(self):
        rows = checklist_rows()
        self.assertGreaterEqual(len(rows), 20)
        sections = {'V1-S': 'State', 'V1-R': 'Recovery', 'V1-E': 'Side effects',
                    'V1-P': 'Permissions', 'V1-O': 'Observability',
                    'V1-V': 'Evaluation', 'V1-C': 'Cost controls'}
        for prefix in sections:
            self.assertTrue(any(row[0].startswith(prefix) for row in rows),
                            f'{sections[prefix]} section must have rows')

    def test_every_gate_file_exists(self):
        for row_id, claim, gate, _proof in checklist_rows():
            self.assertTrue((ROOT / gate).is_file(), f'{row_id}: missing gate {gate}')

    def test_every_proof_identifier_resolves(self):
        known = invariant_ids() | matrix_row_ids()
        for row_id, _claim, _gate, proof in checklist_rows():
            for token in re.findall(r'M\d-(?:F\d+|\d{2})', proof):
                self.assertIn(token, known, f'{row_id}: unresolved proof id {token}')

    def test_no_placeholder_rows(self):
        for row_id, claim, _gate, proof in checklist_rows():
            self.assertGreater(len(claim.strip()), 30, f'{row_id}: claim too thin')
            self.assertTrue(proof.strip(), f'{row_id}: empty proof column')

    def test_residual_gaps_section_exists(self):
        text = CHECKLIST.read_text(encoding='utf-8')
        self.assertIn('## Residual gaps', text)


if __name__ == '__main__':
    unittest.main()
