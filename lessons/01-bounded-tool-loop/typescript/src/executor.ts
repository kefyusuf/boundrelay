import type {ToolDefinition, ToolName} from "./types.js";

export class ToolTimeoutError extends Error {
  readonly tool: ToolName;
  constructor(tool: ToolName) {
    super(`Tool timed out: ${tool}`);
    this.name = "ToolTimeoutError";
    this.tool = tool;
  }
}

export class ToolExecutionError extends Error {
  readonly tool: ToolName;
  constructor(tool: ToolName, message: string) {
    super(message);
    this.name = "ToolExecutionError";
    this.tool = tool;
  }
}

export async function invokeTool(
  definition: ToolDefinition,
  argumentsValue: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  let timeout: ReturnType<typeof setTimeout> | undefined;
  const timedOut = new Promise<never>((_resolve, reject) => {
    timeout = setTimeout(() => reject(new ToolTimeoutError(definition.name)), definition.timeoutMs);
  });
  const invocation = definition.invoke(argumentsValue).catch((error: unknown) => {
    const message = error instanceof Error ? error.message : String(error);
    throw new ToolExecutionError(definition.name, message);
  });
  try {
    return await Promise.race([invocation, timedOut]);
  } finally {
    if (timeout !== undefined) clearTimeout(timeout);
  }
}
