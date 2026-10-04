import {resolve} from "node:path";
import {pathToFileURL} from "node:url";

import {runScenarioCase} from "./runner.js";
import type {RouterMode} from "./types.js";

export interface CliOptions {
  mode: RouterMode;
  caseId: string;
  tracePath: string;
}

const OPTION_NAMES = ["--mode", "--case", "--trace"] as const;
type OptionName = (typeof OPTION_NAMES)[number];

function isOptionName(value: string): value is OptionName {
  return OPTION_NAMES.includes(value as OptionName);
}

function parseArgumentMap(args: string[]): Map<OptionName, string> {
  const values = new Map<OptionName, string>();
  for (let index = 0; index < args.length; index += 2) {
    const option = args[index];
    if (option === undefined || !isOptionName(option)) throw new Error(`Unexpected argument ${option ?? "<end>"}`);
    if (values.has(option)) throw new Error(`Duplicate option ${option}`);
    const value = args[index + 1];
    if (value === undefined || value.startsWith("--")) throw new Error(`Missing required option ${option}`);
    values.set(option, value);
  }
  for (const option of OPTION_NAMES) if (!values.has(option)) throw new Error(`Missing required option ${option}`);
  return values;
}

export function parseCliOptions(args: string[]): CliOptions {
  const values = parseArgumentMap(args);
  const mode = values.get("--mode");
  if (mode !== "code" && mode !== "model") throw new Error("--mode must be code or model");
  return {mode, caseId: values.get("--case") as string, tracePath: values.get("--trace") as string};
}

export async function runCli(
  args: string[],
  stdout: (value: string) => void = (value) => process.stdout.write(value),
  stderr: (value: string) => void = (value) => process.stderr.write(value),
): Promise<number> {
  try {
    const result = await runScenarioCase(parseCliOptions(args));
    stdout(`${JSON.stringify(result)}\n`);
    return 0;
  } catch (error: unknown) {
    stderr(`${error instanceof Error ? error.message : String(error)}\n`);
    return 2;
  }
}

function isEntrypoint(): boolean {
  const entrypoint = process.argv[1];
  return entrypoint !== undefined && import.meta.url === pathToFileURL(resolve(entrypoint)).href;
}

if (isEntrypoint()) {
  void runCli(process.argv.slice(2)).then((code) => { process.exitCode = code; });
}
