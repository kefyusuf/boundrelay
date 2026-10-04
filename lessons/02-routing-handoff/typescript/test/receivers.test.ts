import {describe, expect, it} from "vitest";
import {createReceiverDirectory} from "../src/receivers.js";

describe("M2 deterministic receiver directory", () => {
  it("exposes exactly the three accepted receivers", () => {
    const directory = createReceiverDirectory();
    expect(directory.resolve("billing-specialist")?.name).toBe("billing-specialist");
    expect(directory.resolve("technical-specialist")?.name).toBe("technical-specialist");
    expect(directory.resolve("general-specialist")?.name).toBe("general-specialist");
    expect(directory.resolve("other-specialist")).toBeUndefined();
  });
  it("makes named receivers unavailable without fallback", () => {
    const directory = createReceiverDirectory(["billing-specialist"]);
    expect(directory.resolve("billing-specialist")).toBeUndefined();
    expect(directory.resolve("technical-specialist")?.name).toBe("technical-specialist");
  });
  it("has no dynamic registration or retry API and handlers resolve", async () => {
    const directory = createReceiverDirectory();
    expect("register" in directory).toBe(false);
    expect("retry" in directory).toBe(false);
    await expect(directory.resolve("billing-specialist")?.handle({ticket_id: "TCK-1001", request_text: "hello"})).resolves.toBeUndefined();
  });
});
