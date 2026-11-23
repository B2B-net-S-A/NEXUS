import { describe, expect, it, vi } from "vitest";

import type { FlowBlock } from "@/lib/api/boardTasks";
import {
  buildPersonQueue,
  mergeQueueOrder,
  openOnDashboard,
  personQueueView,
} from "@/lib/dashboard-person-queue";

const NOW = new Date("2026-11-23T12:00:00Z");

function pair(jobId: number, candidateId: number, since: string, name = `Osoba ${candidateId}`) {
  return {
    candidate_id: candidateId,
    candidate_name: name,
    job_id: jobId,
    job_title: `Rekrutacja ${jobId}`,
    job_working_title: null,
    client_name: "Bank Kappa",
    since,
  };
}

function flow(over: Partial<FlowBlock>): FlowBlock {
  return {
    applies: true,
    postings: [],
    postings_total: 0,
    claimed: [],
    screening: [],
    verified: [],
    waiting_client: [],
    waiting_client_days: 7,
    unsigned_contracts: [],
    order_mail_review: 0,
    ...over,
  };
}

const auto = (jobId: number, candidateId: number, waitingDays: number) => ({
  job_id: jobId,
  job_title: `Rekrutacja ${jobId}`,
  job_working_title: null,
  client_name: null,
  candidate_id: candidateId,
  candidate_name: `Od systemu ${candidateId}`,
  score: 70,
  waiting_days: waitingDays,
});

describe("buildPersonQueue — kolejność „Pracuj po kolei” (23.11.2026)", () => {
  it("Screening → Zweryfikowani → od systemu, w każdej liście najdłużej czekający pierwsi", () => {
    const queue = buildPersonQueue(
      flow({
        screening: [pair(1, 11, "2026-11-20T08:00:00Z"), pair(2, 12, "2026-10-19T08:00:00Z")],
        verified: [pair(3, 13, "2026-11-22T08:00:00Z"), pair(1, 14, "2026-11-01T08:00:00Z")],
        autofill_decisions: [auto(4, 15, 2), auto(5, 16, 5)],
      }),
      NOW,
    );
    expect(queue.map((e) => e.key)).toEqual(["2:12", "1:11", "1:14", "3:13", "5:16", "4:15"]);
    expect(queue.map((e) => e.list)).toEqual([
      "screening",
      "screening",
      "verified",
      "verified",
      "autofill",
      "autofill",
    ]);
    expect(queue[0].waiting).toMatch(/^od /);
    expect(queue[4].waiting).toBe("5 dni");
  });

  it("para w dwóch listach liczy się raz — wygrywa pierwsza lista", () => {
    const queue = buildPersonQueue(
      flow({ screening: [pair(1, 11, "2026-11-20T08:00:00Z")], verified: [pair(1, 11, "2026-11-21T08:00:00Z")] }),
      NOW,
    );
    expect(queue).toHaveLength(1);
    expect(queue[0].list).toBe("screening");
  });

  it("pusta lista i brak bloku przepływu → pusta kolejka", () => {
    expect(buildPersonQueue(null)).toEqual([]);
    expect(buildPersonQueue(flow({}))).toEqual([]);
  });
});

describe("mergeQueueOrder — kolejność trwa przez odświeżenia", () => {
  it("znane osoby zostają na miejscach (także te, które wyszły), nowe na końcu", () => {
    const fresh = buildPersonQueue(
      flow({ screening: [pair(9, 99, "2026-10-01T08:00:00Z"), pair(1, 11, "2026-11-20T08:00:00Z")] }),
      NOW,
    );
    expect(mergeQueueOrder(["2:12", "1:11"], fresh)).toEqual(["2:12", "1:11", "9:99"]);
  });
});

describe("personQueueView — kto dalej", () => {
  const entries = buildPersonQueue(
    flow({
      screening: [pair(1, 11, "2026-11-01T08:00:00Z"), pair(2, 12, "2026-11-02T08:00:00Z")],
      verified: [pair(3, 13, "2026-11-03T08:00:00Z")],
    }),
    NOW,
  );
  const order = entries.map((e) => e.key);

  it("osoba w kolejce: pozycja, poprzednia i następna przez różne rekrutacje", () => {
    const view = personQueueView(order, entries, "2:12", "2:12");
    expect(view.position).toBe(2);
    expect(view.live).toHaveLength(3);
    expect(view.previous?.key).toBe("1:11");
    expect(view.next?.key).toBe("3:13");
  });

  it("osoba zamknięta z panelu (`done`) znika od razu, dalej = kto stał za nią", () => {
    const view = personQueueView(order, entries, "1:11", "1:11", new Set(["1:11"]));
    expect(view.position).toBeNull();
    expect(view.live.map((e) => e.key)).toEqual(["2:12", "3:13"]);
    expect(view.next?.key).toBe("2:12");
  });

  it("osoba wyszła z listy po odświeżeniu (np. przesunięta dalej) — panel zostaje, „Dalej” od jej miejsca", () => {
    const afterMove = entries.filter((e) => e.key !== "2:12");
    const view = personQueueView(order, afterMove, "2:12", "2:12");
    expect(view.current).toBeNull();
    expect(view.next?.key).toBe("3:13");
  });

  it("osoba spoza kolejki (otwarta z wnętrza panelu) — „Dalej” od kotwicy", () => {
    const view = personQueueView(order, entries, "1:77", "1:11");
    expect(view.position).toBeNull();
    expect(view.next?.key).toBe("2:12");
  });

  it("ostatnia osoba nie ma następnej", () => {
    expect(personQueueView(order, entries, "3:13", "3:13").next).toBeNull();
  });
});

describe("openOnDashboard — link zostaje linkiem", () => {
  const event = (over: Record<string, unknown> = {}) => ({
    defaultPrevented: false,
    button: 0,
    metaKey: false,
    ctrlKey: false,
    shiftKey: false,
    altKey: false,
    preventDefault: vi.fn(),
    ...over,
  });

  it("zwykły klik otwiera panel na pulpicie", () => {
    const e = event();
    const open = vi.fn();
    openOnDashboard(e, open);
    expect(open).toHaveBeenCalled();
    expect(e.preventDefault).toHaveBeenCalled();
  });

  it.each([{ metaKey: true }, { ctrlKey: true }, { shiftKey: true }, { button: 1 }])(
    "klik z modyfikatorem %o otwiera Tablicę jak dotąd",
    (over) => {
      const e = event(over);
      const open = vi.fn();
      openOnDashboard(e, open);
      expect(open).not.toHaveBeenCalled();
      expect(e.preventDefault).not.toHaveBeenCalled();
    },
  );
});
