import {readFileSync} from "node:fs";

import {parse} from "yaml";

import {FAKE_TOOLS_PATH} from "./paths.js";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

interface FakeToolData {
  orders: Record<string, Record<string, unknown>>;
  shipments: Record<string, Record<string, unknown>>;
}

function loadFakeToolData(path: string = FAKE_TOOLS_PATH): FakeToolData {
  const document = parse(readFileSync(path, "utf8"));
  if (!isRecord(document) || document.schema_version !== "1.0" || document.scenario_id !== "order-investigation") {
    throw new Error("Unsupported M1 fake-tool fixture.");
  }
  if (!isRecord(document.orders) || !isRecord(document.shipments)) {
    throw new Error("Fake-tool fixture must define orders and shipments.");
  }
  const parseRecords = (value: Record<string, unknown>, label: string): Record<string, Record<string, unknown>> => {
    const result: Record<string, Record<string, unknown>> = {};
    for (const [id, entry] of Object.entries(value)) {
      if (!isRecord(entry)) {
        throw new Error(`${label} ${id} must be an object.`);
      }
      result[id] = structuredClone(entry);
    }
    return result;
  };
  return {orders: parseRecords(document.orders, "Order"), shipments: parseRecords(document.shipments, "Shipment")};
}

const data = loadFakeToolData();

async function invokeEntry(
  entry: Record<string, unknown>,
  label: string,
): Promise<Record<string, unknown>> {
  if (entry.behavior === "timeout") {
    return new Promise<Record<string, unknown>>(() => {});
  }
  if (entry.behavior === "failure") {
    throw new Error(`${label} scripted failure.`);
  }
  if (!isRecord(entry.output)) {
    throw new Error(`${label} fixture must contain output or behavior.`);
  }
  return structuredClone(entry.output);
}

export async function lookupOrder(argumentsValue: Record<string, unknown>): Promise<Record<string, unknown>> {
  const orderId = argumentsValue.order_id;
  if (typeof orderId !== "string" || data.orders[orderId] === undefined) {
    throw new Error(`Unknown order fixture: ${String(orderId)}`);
  }
  return invokeEntry(data.orders[orderId], `Order ${orderId}`);
}

export async function lookupShipment(argumentsValue: Record<string, unknown>): Promise<Record<string, unknown>> {
  const shipmentId = argumentsValue.shipment_id;
  if (typeof shipmentId !== "string" || data.shipments[shipmentId] === undefined) {
    throw new Error(`Unknown shipment fixture: ${String(shipmentId)}`);
  }
  return invokeEntry(data.shipments[shipmentId], `Shipment ${shipmentId}`);
}
