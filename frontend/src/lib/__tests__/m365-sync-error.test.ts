import { describe, expect, it } from "vitest";
import { m365SyncErrorMessage } from "@/lib/m365-sync-error";

describe("m365SyncErrorMessage (UAT B61)", () => {
  it("throttling is a transient warning with no action required", () => {
    const message = m365SyncErrorMessage("graph_throttled");
    expect(message.variant).toBe("warning");
    expect(message.description).toContain("automatycznie");
    expect(`${message.title} ${message.description}`).not.toMatch(/GraphRequestError|retry_after/);
  });
  it("lost authorisation asks to reconnect", () => {
    const message = m365SyncErrorMessage("reauth_required");
    expect(message.variant).toBe("error");
    expect(message.description).toContain("połącz");
  });
  it("unknown or missing code falls back to a Polish generic message", () => {
    expect(m365SyncErrorMessage("unknown").title).toBe("Błąd synchronizacji");
    expect(m365SyncErrorMessage(undefined).title).toBe("Błąd synchronizacji");
  });
});
