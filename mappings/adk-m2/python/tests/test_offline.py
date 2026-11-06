"""Offline proof: the ADK machinery runs with no network and no client.

The scripted router model is constructed purely from the fixture
decisions; the offline proof patches every HTTP client constructor
(httpx, requests, the Google GenAI client) to explode and runs the
ADK Runner end-to-end anyway.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from boundrelay_m2_adk import fixtures, mapping


class ScriptedModelPurityTests(unittest.TestCase):
    def test_scripted_model_is_an_adk_base_llm(self):
        from google.adk.models.base_llm import BaseLlm
        model = mapping.build_scripted_model(
            fixtures.load_case("model-technical-handoff"),
            mapping.RunLedger())
        self.assertIsInstance(model, BaseLlm)
        self.assertEqual(model.model, "boundrelay-scripted-router")

    def test_scripted_model_carries_no_client(self):
        model = mapping.build_scripted_model(
            fixtures.load_case("model-technical-handoff"),
            mapping.RunLedger())
        for attribute in ("client", "_client", "api_client", "_api_client",
                          "models"):
            self.assertFalse(hasattr(model, attribute),
                             f"scripted model must not carry {attribute}")


class NoNetworkTests(unittest.TestCase):
    """Every HTTP client constructor explodes; the run completes anyway."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trace = str(Path(self.tmp.name) / "trace.jsonl")

    def _explode(self, name):
        return mock.patch(name, side_effect=AssertionError(
            f"{name} must never be constructed: the mapping is offline"))

    def test_all_five_cases_complete_with_http_clients_disabled(self):
        for key in fixtures.PARITY_CASE_KEYS:
            with self.subTest(case=key):
                with self._explode("httpx.Client"), \
                        self._explode("httpx.AsyncClient"), \
                        self._explode("requests.Session"), \
                        self._explode("google.genai.client.Client"):
                    result = mapping.run_case(key, self.trace)
                self.assertIn(result["status"], ("SUCCEEDED", "FAILED"))

    def test_runs_complete_without_any_google_api_key(self):
        environment = dict(os.environ)
        try:
            for name in ("GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY",
                         "GOOGLE_CLOUD_PROJECT", "OTEL_EXPORTER_OTLP_ENDPOINT"):
                os.environ.pop(name, None)
            result = mapping.run_case("model-technical-handoff", self.trace)
            self.assertEqual(result["status"], "SUCCEEDED")
        finally:
            os.environ.clear()
            os.environ.update(environment)


if __name__ == "__main__":
    unittest.main()
