"""Offline proof: the SDK machinery runs with no network and no client.

The scripted model provider is constructed purely from the fixture
turns; the offline proof patches every HTTP client constructor (httpx
and the OpenAI SDKs) to explode and runs the Agent/Runner machinery
end-to-end anyway.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from boundrelay_m1_openai import fixtures, mapping


class ScriptedProviderPurityTests(unittest.TestCase):
    def test_provider_resolves_the_scripted_model_without_a_client(self):
        ledger = mapping.RunLedger(max_steps=1, max_tokens=10)
        model = mapping.ScriptedAgentModel(
            fixtures.load_case("agent-unknown-tool").turns, ledger)
        provider = mapping.ScriptedModelProvider(model)
        self.assertIs(provider.get_model("gpt-4o"), model)
        self.assertIs(provider.get_model(None), model)
        self.assertEqual(model.remaining_turns, 1)
        for attribute in ("client", "_client", "async_client", "_async_client"):
            self.assertFalse(hasattr(model, attribute),
                             f"scripted model must not carry {attribute}")

    def test_model_provider_is_an_sdk_model_implementation(self):
        from agents.models.interface import Model, ModelProvider
        ledger = mapping.RunLedger(max_steps=1, max_tokens=10)
        model = mapping.ScriptedAgentModel([], ledger)
        self.assertIsInstance(model, Model)
        self.assertIsInstance(mapping.ScriptedModelProvider(model), ModelProvider)


class NoNetworkTests(unittest.TestCase):
    """Every HTTP client constructor explodes; the run completes anyway."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trace = str(Path(self.tmp.name) / "trace.jsonl")

    def _explode(self, name):
        return mock.patch(name, side_effect=AssertionError(
            f"{name} must never be constructed: the mapping is offline"))

    def test_runs_complete_with_all_http_clients_disabled(self):
        cases = ("agent-delayed-shipment", "agent-unknown-tool",
                 "agent-step-budget", "agent-token-budget")
        for key in cases:
            with self.subTest(case=key):
                with self._explode("httpx.Client"), \
                        self._explode("httpx.AsyncClient"), \
                        self._explode("openai.OpenAI"), \
                        self._explode("openai.AsyncOpenAI"):
                    result = mapping.run_case(key, self.trace)
                self.assertIn(result["status"], ("SUCCEEDED", "FAILED"))

    def test_runs_complete_without_an_openai_api_key(self):
        environment = dict(os.environ)
        try:
            os.environ.pop("OPENAI_API_KEY", None)
            result = mapping.run_case("agent-delayed-shipment", self.trace)
            self.assertEqual(result["status"], "SUCCEEDED")
        finally:
            os.environ.clear()
            os.environ.update(environment)


if __name__ == "__main__":
    unittest.main()
