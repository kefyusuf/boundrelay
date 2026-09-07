import {mkdtempSync, writeFileSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";

import {describe, expect, it} from "vitest";

import {loadScenario} from "../src/scenario.js";

function writeScenario(routes: string[]): string {
  const directory = mkdtempSync(join(tmpdir(), "boundrelay-m0-scenario-"));
  const path = join(directory, "scenario.yaml");
  writeFileSync(
    path,
    [
      'schema_version: "1.0"',
      "scenario_id: support-triage",
      `routes: [${routes.join(", ")}]`,
      "cases:",
      "  - id: billing",
      "    request: charged twice",
      "    expected_route: billing",
    ].join("\n") + "\n",
    "utf8",
  );
  return path;
}

function expectRejectedRoutes(routes: string[]): void {
  let thrown: unknown;
  try {
    loadScenario(writeScenario(routes));
  } catch (error) {
    thrown = error;
  }
  expect(thrown instanceof Error).toBe(true);
  expect((thrown as Error).message).toBe("Scenario routes must match the canonical M0 routes.");
}

describe("scenario loading", () => {
  it("rejects reordered route declarations", () => {
    expectRejectedRoutes(["technical", "billing", "general"]);
  });

  it("rejects duplicated route declarations", () => {
    expectRejectedRoutes(["billing", "billing", "general"]);
  });
});
