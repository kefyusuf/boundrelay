import unittest
from boundrelay_m5.paths import ROOT
from boundrelay_m5.idempotency import effect_digest, effect_key

PAYLOAD = {'operation': 'cancel-and-refund', 'order_id': 'ORD-1001',
           'refund_amount_cents': 4200, 'currency': 'EUR'}


class FoundationsTests(unittest.TestCase):
    def test_repository_paths_resolve_real_fixtures(self):
        self.assertTrue((ROOT / 'fixtures/scenarios/order-closure.yaml').exists())

    def test_m5_closed_contracts_are_present(self):
        for relative in ('contracts/state/order-closure-run-state.schema.json',
                         'contracts/results/order-closure-result.schema.json',
                         'contracts/effects/order-closure-effect.schema.json',
                         'contracts/audit/order-closure-audit.schema.json',
                         'contracts/events/run-event.schema.json'):
            self.assertTrue((ROOT / relative).exists(), relative)

    def test_effect_key_is_deterministic_and_stable(self):
        self.assertEqual(effect_key(PAYLOAD), 'cancel-and-refund:ORD-1001')
        self.assertEqual(effect_key(PAYLOAD), effect_key(dict(PAYLOAD)))
        self.assertRegex(effect_digest(PAYLOAD), r'^[0-9a-f]{64}$')
        self.assertEqual(effect_digest(PAYLOAD), effect_digest(dict(PAYLOAD)))
        other = {**PAYLOAD, 'order_id': 'ORD-1002'}
        self.assertEqual(effect_key(other), 'cancel-and-refund:ORD-1002')
        self.assertNotEqual(effect_key(other), effect_key(PAYLOAD))
        self.assertNotEqual(effect_digest(other), effect_digest(PAYLOAD))
    def test_effect_digest_binds_every_payload_field(self):
        amount = {**PAYLOAD, 'refund_amount_cents': 4300}
        self.assertEqual(effect_key(amount), effect_key(PAYLOAD))
        self.assertNotEqual(effect_digest(amount), effect_digest(PAYLOAD))
        currency = {**PAYLOAD, 'currency': 'USD'}
        self.assertNotEqual(effect_digest(currency), effect_digest(PAYLOAD))
        reordered = {'order_id': 'ORD-1001', 'currency': 'EUR',
                     'refund_amount_cents': 4200, 'operation': 'cancel-and-refund'}
        self.assertEqual(effect_digest(PAYLOAD), effect_digest(reordered))

