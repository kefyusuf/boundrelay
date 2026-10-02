import {it, expect} from "vitest";
import {mkdtemp, readFile, rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {runScenarioCase} from "../src/runner.js";
import {loadScenario} from "../src/scenario.js";
import type {ReceiverDirectory, ReceiverInput, ReceiverName} from "../src/types.js";

async function withTrace(test: (path: string) => Promise<void>) {
  const dir = await mkdtemp(join(tmpdir(), "boundrelay-m2-"));
  try {await test(join(dir, "trace.jsonl"));} finally {await rm(dir, {recursive: true, force: true});}
}
const readEvents = async (path: string) => (await readFile(path, "utf8")).trimEnd().split("\n").map(s => JSON.parse(s));
for (const c of loadScenario().cases) it(`pins lifecycle and actual invocation for ${c.id}`, () => withTrace(async tracePath => {
  const invoked: ReceiverInput[] = [];
  const resolved: string[] = [];
  const directory: ReceiverDirectory = {resolve(name) {
    resolved.push(name);
    if (c.id === "handoff-receiver-unavailable") return undefined;
    return {name: name as ReceiverName, async handle(input) {invoked.push(input);}};
  }};
  const result = await runScenarioCase({mode: c.router_mode, caseId: c.id, tracePath, receiverDirectory: directory});
  expect(result).toMatchObject({case_id: c.id, router_mode: c.router_mode, status: c.expected_status, proposed_route: c.expected_proposed_route, selected_route: c.expected_selected_route, receiver: c.expected_receiver, fallback_applied: c.expected_fallback_applied, specialist_invoked: c.expected_specialist_invoked, failure_code: c.expected_failure_code});
  expect(invoked).toEqual(c.expected_specialist_invoked ? [{ticket_id: c.ticket_id, request_text: c.request}] : []);
  expect(resolved).toEqual(c.id === "handoff-context-loss" ? [] : [c.expected_receiver]);
  const events = await readEvents(tracePath);
  const expected = ["run.created", "run.started", ...(c.router_mode === "model" ? ["model.requested", "model.completed"] : []), "route.selected", "handoff.requested", c.expected_specialist_invoked ? "handoff.accepted" : "handoff.rejected", c.expected_specialist_invoked ? "run.completed" : "run.failed"];
  expect(events.map(e => e.type)).toEqual(expected);
  expect(events.map(e => e.sequence)).toEqual(expected.map((_, i) => i + 1));
  expect(events.every(e => e.run_id === result.run_id)).toBe(true);
  const request = events.find(e => e.type === "handoff.requested").data;
  expect(request.sender_intent).toEqual({route: c.expected_proposed_route, confidence: c.expected_confidence, policy_outcome: c.expected_policy_outcome});
  expect(request.receiver_input).toEqual(c.id === "handoff-context-loss" ? {ticket_id: c.ticket_id} : {ticket_id: c.ticket_id, request_text: c.request});
  expect(events.at(-2).data.handoff_id).toBe(request.handoff_id);
}));
it("rejects malformed route before any receiver resolution", () => withTrace(async tracePath => {
  for (const decision of [{route: "other", confidence: 1}, {route: "billing", confidence: NaN}, {route: "billing", confidence: .9, receiver: "general-specialist"}]) {
    let resolutions = 0;
    const result = await runScenarioCase({mode: "model", caseId: "model-technical-handoff", tracePath, routeProvider: {async nextDecision() {return decision;}}, receiverDirectory: {resolve() {resolutions++; return undefined;}}});
    expect(result.failure_code).toBe("INVALID_ROUTE_DECISION");
    expect(result.proposed_route).toBeNull();
    expect(resolutions).toBe(0);
    expect((await readEvents(tracePath)).map(e => e.type)).toEqual(["run.created", "run.started", "model.requested", "model.completed", "route.rejected", "run.failed"]);
  }
}));
it("propagates receiver exceptions without retry", () => withTrace(async tracePath => {
  let calls = 0;
  await expect(runScenarioCase({mode: "code", caseId: "code-billing-handoff", tracePath, receiverDirectory: {resolve() {return {name: "billing-specialist", async handle() {calls++; throw new Error("receiver bug");}};}}})).rejects.toThrow("receiver bug");
  expect(calls).toBe(1);
}));
it("rejects mismatched mode and unknown case", () => withTrace(async tracePath => {
  await expect(runScenarioCase({mode: "code", caseId: "model-technical-handoff", tracePath})).rejects.toThrow();
  await expect(runScenarioCase({mode: "code", caseId: "unknown", tracePath})).rejects.toThrow();
}));
