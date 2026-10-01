import unittest

from boundrelay_m2.receivers import create_receiver_directory
from boundrelay_m2.types import ReceiverInput


class ReceiverTests(unittest.IsolatedAsyncioTestCase):
    def test_exposes_exact_three_receivers_and_unknown_is_absent(self) -> None:
        directory = create_receiver_directory()
        self.assertEqual(directory.resolve("billing-specialist").name, "billing-specialist")
        self.assertEqual(directory.resolve("technical-specialist").name, "technical-specialist")
        self.assertEqual(directory.resolve("general-specialist").name, "general-specialist")
        self.assertIsNone(directory.resolve("other-specialist"))

    def test_named_receiver_can_be_unavailable_without_fallback(self) -> None:
        directory = create_receiver_directory(("billing-specialist",))
        self.assertIsNone(directory.resolve("billing-specialist"))
        self.assertEqual(directory.resolve("technical-specialist").name, "technical-specialist")

    async def test_directory_has_no_registration_or_retry_api_and_handlers_resolve(self) -> None:
        directory = create_receiver_directory()
        self.assertFalse(hasattr(directory, "register"))
        self.assertFalse(hasattr(directory, "retry"))
        receiver = directory.resolve("billing-specialist")
        self.assertIsNotNone(receiver)
        assert receiver is not None
        self.assertIsNone(await receiver.handle(ReceiverInput("TCK-1001", "hello")))


if __name__ == "__main__":
    unittest.main()
