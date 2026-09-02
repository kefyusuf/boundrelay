import type {SpecialistDispatcher, SpecialistInvocation} from "./types.js";

export class RecordingSpecialistDispatcher implements SpecialistDispatcher {
  readonly #invocations: SpecialistInvocation[] = [];

  get invocations(): readonly SpecialistInvocation[] {
    return this.#invocations.map((invocation) => structuredClone(invocation));
  }

  async dispatch(invocation: SpecialistInvocation): Promise<void> {
    this.#invocations.push(Object.freeze(structuredClone(invocation)));
  }
}
