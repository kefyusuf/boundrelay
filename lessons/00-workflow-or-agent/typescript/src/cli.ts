import {runScenarioCase} from "./runner.js";
import type {RunMode} from "./types.js";

interface CliOptions {
  mode: RunMode;
  caseId: string;
  tracePath: string;
}

function readOption(args: string[], name: string): string {
  const index = args.indexOf(name);
  const value = index >= 0 ? args[index + 1] : undefined;
  if (value === undefined || value.startsWith("--")) {
    throw new Error(`Missing required option ${name}`);
  }
  return value;
}

export function parseCliOptions(args: string[]): CliOptions {
  const mode = readOption(args, "--mode");
  if (mode !== "deterministic" && mode !== "model") {
    throw new Error("--mode must be deterministic or model");
  }
  return {
    mode,
    caseId: readOption(args, "--case"),
    tracePath: readOption(args, "--trace"),
  };
}

async function main(): Promise<void> {
  const options = parseCliOptions(process.argv.slice(2));
  const result = await runScenarioCase(options);
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`${message}\n`);
  process.exitCode = 2;
});
