import unittest

from tools.parity.verify_m0 import _assert_expected_behavior


class RejectionContractTests(unittest.TestCase):
    def test_route_rejected_failure_code_must_match_the_result(self) -> None:
        with self.assertRaisesRegex(AssertionError, "route.rejected"):
            _assert_expected_behavior(
                case={"expected_failure_code": "INVALID_ROUTE_DECISION"},
                result={
                    "status": "FAILED",
                    "selected_route": None,
                    "specialist_invoked": False,
                    "failure_code": "INVALID_ROUTE_DECISION",
                },
                events=[
                    {
                        "type": "route.rejected",
                        "data": {
                            "route": "unknown-specialist",
                            "failure_code": "WRONG_FAILURE_CODE",
                        },
                    },
                    {
                        "type": "step.failed",
                        "data": {
                            "step": "classify",
                            "failure_code": "INVALID_ROUTE_DECISION",
                        },
                    },
                    {
                        "type": "run.failed",
                        "data": {
                            "status": "FAILED",
                            "failure_code": "INVALID_ROUTE_DECISION",
                        },
                    },
                ],
                label="Python invalid-model-route/model",
            )


if __name__ == "__main__":
    unittest.main()
