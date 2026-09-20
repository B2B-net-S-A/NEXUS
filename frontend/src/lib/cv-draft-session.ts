/** Serialize autosave and approval without replacing edits made during a request. */
export type CvSaveState = "saved" | "unsaved" | "saving" | "error" | "finalizing" | "finalized";

/** Wynik zatwierdzenia wraz z werdyktem niezależnej kontroli AI (0327).
 *  Kontrola jest doradcza: uwagi NIE wstrzymują zatwierdzenia, ale muszą
 *  dojechać do rekrutera, więc podróżują razem z wynikiem. */
export type CvFinalizeOutcome = {
  edit_revision: number;
  content_review_status?: string | null;
  content_review_findings?: number | null;
};

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
      finalize: (html: string, revision: number) => Promise<CvFinalizeOutcome>;
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
      if (this.html !== this.persistedInput) {
        const saved = await this.transport.save(this.html, this.revision);
        this.revision = saved.edit_revision;
        this.persistedInput = this.html;
      }
      const result = await this.transport.finalize(this.html, this.revision);
      this.revision = result.edit_revision;
      this.persistedInput = this.html;
      this.notify("finalized");
      return result;
    } catch (error) {
      this.notify("error");
      throw error;
    }
  }
}
