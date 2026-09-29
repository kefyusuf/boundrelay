import asyncio
import unittest

from boundrelay_m1.tool_registry import create_fake_tool_registry


class ToolTests(unittest.IsolatedAsyncioTestCase):
    def test_registry_exposes_exactly_two_read_only_tools(self) -> None:
        registry = create_fake_tool_registry()
        order = registry.resolve("lookup_order")
        shipment = registry.resolve("lookup_shipment")
        self.assertIsNotNone(order)
        self.assertIsNotNone(shipment)
        assert order is not None
        assert shipment is not None
        self.assertEqual(order.side_effect, "READ_ONLY")
        self.assertEqual(shipment.side_effect, "READ_ONLY")
        self.assertEqual(order.timeout_ms, 100)
        self.assertEqual(shipment.timeout_ms, 100)
        self.assertIsNone(registry.resolve("lookup_customer"))

    def test_registry_uses_shared_argument_contracts(self) -> None:
        registry = create_fake_tool_registry()
        order = registry.resolve("lookup_order")
        shipment = registry.resolve("lookup_shipment")
        assert order is not None
        assert shipment is not None
        self.assertTrue(order.validate_arguments({"order_id": "ORD-1001"}).ok)
        self.assertFalse(order.validate_arguments({"order_id": "1001"}).ok)
        self.assertTrue(shipment.validate_arguments({"shipment_id": "SHP-1001"}).ok)

    async def test_normal_tools_return_canonical_read_only_observations(self) -> None:
        registry = create_fake_tool_registry()
        order = registry.resolve("lookup_order")
        shipment = registry.resolve("lookup_shipment")
        assert order is not None
        assert shipment is not None
        self.assertEqual(await order.invoke({"order_id": "ORD-1001"}), {
            "order_id": "ORD-1001",
            "status": "SHIPPED",
            "shipment_id": "SHP-1001",
        })
        self.assertEqual(await shipment.invoke({"shipment_id": "SHP-1001"}), {
            "shipment_id": "SHP-1001",
            "status": "DELAYED",
            "reason": "WEATHER",
        })

    async def test_timeout_fixture_waits_until_runtime_cancels_it(self) -> None:
        registry = create_fake_tool_registry()
        order = registry.resolve("lookup_order")
        assert order is not None
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(order.invoke({"order_id": "ORD-9001"}), timeout=0.01)

    async def test_failure_fixture_raises_deterministically(self) -> None:
        registry = create_fake_tool_registry()
        order = registry.resolve("lookup_order")
        assert order is not None
        with self.assertRaisesRegex(RuntimeError, "scripted failure"):
            await order.invoke({"order_id": "ORD-9002"})


if __name__ == "__main__":
    unittest.main()
