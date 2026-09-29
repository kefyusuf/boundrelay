import {describe, expect, it} from "vitest";

import {createFakeToolRegistry} from "../src/tool-registry.js";

describe("M1 read-only tool registry", () => {
  it("exposes exactly the two accepted read-only tools", () => {
    const registry = createFakeToolRegistry();
    expect(registry.resolve("lookup_order")?.sideEffect).toBe("READ_ONLY");
    expect(registry.resolve("lookup_shipment")?.sideEffect).toBe("READ_ONLY");
    expect(registry.resolve("lookup_order")?.timeoutMs).toBe(100);
    expect(registry.resolve("lookup_shipment")?.timeoutMs).toBe(100);
    expect(registry.resolve("lookup_customer")).toBeUndefined();
  });

  it("uses shared argument schemas at each registered tool boundary", () => {
    const registry = createFakeToolRegistry();
    expect(registry.resolve("lookup_order")?.validateArguments({order_id: "ORD-1001"}).ok).toBe(true);
    expect(registry.resolve("lookup_order")?.validateArguments({order_id: "1001"}).ok).toBe(false);
    expect(registry.resolve("lookup_shipment")?.validateArguments({shipment_id: "SHP-1001"}).ok).toBe(true);
  });

  it("returns the canonical fake read-only observations", async () => {
    const registry = createFakeToolRegistry();
    await expect(registry.resolve("lookup_order")?.invoke({order_id: "ORD-1001"})).resolves.toEqual({
      order_id: "ORD-1001",
      status: "SHIPPED",
      shipment_id: "SHP-1001",
    });
    await expect(registry.resolve("lookup_shipment")?.invoke({shipment_id: "SHP-1001"})).resolves.toEqual({
      shipment_id: "SHP-1001",
      status: "DELAYED",
      reason: "WEATHER",
    });
  });
});
