import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const opened = vi.fn();

vi.mock("@/lib/job-proposals-api", () => ({
  jobProposalsApi: { opened: (...a: unknown[]) => opened(...a) },
}));

import { proposalInboxOpenedKey, recordProposalInboxOpened } from "@/lib/proposal-inbox-opened";

const MORNING = new Date("2026-10-07T07:00:00Z");
const NEXT_DAY = new Date("2026-10-08T07:00:00Z");

beforeEach(() => {
  opened.mockReset();
  opened.mockResolvedValue({ recorded: true });
  window.localStorage.clear();
  window.history.replaceState(null, "", "/jobs/5");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("recordProposalInboxOpened — otwarcie „Do przejrzenia”", () => {
  it("najwyżej raz na rekrutację na dzień; następnego dnia znowu", () => {
    recordProposalInboxOpened(5, MORNING);
    recordProposalInboxOpened(5, MORNING);
    recordProposalInboxOpened(6, MORNING);
    expect(opened.mock.calls).toEqual([[5], [6]]);
    expect(window.localStorage.getItem(proposalInboxOpenedKey(5))).toBe("2026-10-07");

    recordProposalInboxOpened(5, NEXT_DAY);
    expect(opened).toHaveBeenCalledTimes(3);
  });

  it("błąd serwera jest połykany — bez wyjątku i bez czekania", async () => {
    opened.mockRejectedValue(new Error("500"));
    expect(() => recordProposalInboxOpened(5, MORNING)).not.toThrow();
    await Promise.resolve();
  });

  it("niedostępna pamięć przeglądarki nie blokuje pomiaru", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => recordProposalInboxOpened(5, MORNING)).not.toThrow();
    expect(opened).toHaveBeenCalledWith(5);
  });

  it("harness /preview/* nic nie wysyła", () => {
    window.history.replaceState(null, "", "/preview/job-detail");
    recordProposalInboxOpened(5, MORNING);
    expect(opened).not.toHaveBeenCalled();
    expect(window.localStorage.getItem(proposalInboxOpenedKey(5))).toBeNull();
  });
});
