/** Serialize autosave and approval without replacing edits made during a request. */
export type CvSaveState = "saved" | "unsaved" | "saving" | "error" | "finalizing" | "finalized";

export class CvDraftSession {
  revision: number;
  html: string;
  state: CvSaveState;
  private persistedInput: string;
  private pending: Promise<void> | null = null;

  constructor(
    html: string,
    revision: number,
    finalized: boolean,
    private readonly transport: {
      save: (html: string, revision: number) => Promise<{ edit_revision: number }>;
      finalize: (html: string, revision: number) => Promise<{ edit_revision: number }>;
    },
    private readonly changed: (state: CvSaveState) => void,
  ) {
    this.html = this.persistedInput = html;
    this.revision = revision;
    this.state = finalized ? "finalized" : "saved";
  }

  private notify(state: CvSaveState) {
    this.state = state;
    this.changed(state);
  }

  edit(html: string) {
    if (this.state === "finalizing" || this.state === "finalized") return;
    this.html = html;
    this.notify(this.pending ? "saving" : html === this.persistedInput ? "saved" : "unsaved");
  }

  async settle() {
    if (this.pending) await this.pending;
  }

  async save() {
    if (this.pending) return this.pending;
    if (this.state === "finalizing" || this.state === "finalized" || this.html === this.persistedInput) return;
    const input = this.html;
    this.notify("saving");
    this.pending = (async () => {
      try {
        const result = await this.transport.save(input, this.revision);
        this.revision = result.edit_revision;
        this.persistedInput = input;
        if (this.state !== "finalizing") this.notify(this.html === input ? "saved" : "unsaved");
      } catch (error) {
        this.notify("error");
        throw error;
      } finally {
        this.pending = null;
      }
    })();
    return this.pending;
  }

  async finalize() {
    if (this.state === "finalizing" || this.state === "finalized") return;
    this.notify("finalizing");
    try {
      await this.settle();
      const result = await this.transport.finalize(this.html, this.revision);
      this.revision = result.edit_revision;
      this.persistedInput = this.html;
      this.notify("finalized");
    } catch (error) {
      this.notify("error");
      throw error;
    }
  }
}
