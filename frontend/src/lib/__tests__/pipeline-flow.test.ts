/**
 * Kolejki kroków 05 i 06 oraz bramka ruchu (program „flow w języku C2", PR 6/7).
 */

import { describe, expect, it } from "vitest";

import {
  countAtClient,
  findStageColumn,
  itemFullName,
  moveBlockedReason,
  selectPendingVerifications,
  selectScreeningQueue,
  selectVerifiedQueue,
} from "@/lib/pipeline-flow";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";

function item(overrides: Partial<KanbanItem> = {}): KanbanItem {
  return {
    id: overrides.id ?? 1,
    candidate_id: overrides.candidate_id ?? 100,
    stage: overrides.stage ?? "screening",
    name: "Jan",
    lastname: "Kowalski",
    ...overrides,
  };
}

function col(overrides: Partial<KanbanColumn> = {}): KanbanColumn {
  const items = overrides.items ?? [];
  return {
    stage: overrides.stage ?? "screening",
    name: overrides.name ?? "Screening",
    category: overrides.category ?? "internal",
    count: items.length,
    items,
    ...overrides,
  };
}

const board: KanbanColumn[] = [
  col({
    stage: "screening",
    name: "Screening",
    stage_def_id: 3,
    items: [item({ id: 11, candidate_id: 111 }), item({ id: 12, candidate_id: 112 })],
  }),
  col({
    stage: "verified",
    name: "Zweryfikowany",
    stage_def_id: 4,
    items: [
      item({ id: 21, candidate_id: 121, stage: "verified" }),
      item({
        id: 22,
        candidate_id: 122,
        stage: "verified",
        verification_status: "pending",
      }),
    ],
  }),
  col({
    stage: "cv_sent",
    name: "CV Wysłane",
    stage_def_id: 5,
    items: [item({ id: 31, candidate_id: 131, stage: "cv_sent" })],
  }),
  col({
    stage: "client_interview",
    name: "Interview Klient",
    category: "external",
    stage_def_id: 6,
    items: [item({ id: 41, candidate_id: 141, stage: "client_interview" })],
  }),
  col({
    stage: "rejected",
    name: "Odrzucony",
    category: "terminal",
    terminal_type: "rejected",
    stage_def_id: 9,
    items: [
      item({
        id: 51,
        candidate_id: 151,
        stage: "rejected",
        verification_status: "pending",
      }),
    ],
  }),
];

describe("findStageColumn", () => {
  it("rozpoznaje kolumnę po legacy-enumie, nie po nazwie", () => {
    expect(findStageColumn(board, "cv_sent")?.name).toBe("CV Wysłane");
    expect(findStageColumn(board, "nie_ma_takiego")).toBeNull();
  });
});

describe("selectScreeningQueue", () => {
  it("bierze wyłącznie etap „Screening”, w kolejności z tablicy", () => {
    const queue = selectScreeningQueue(board);
    expect(queue.map((e) => e.item.id)).toEqual([11, 12]);
    expect(queue[0].colId).toBe("def:3");
  });

  it("nie wciąga etapów zewnętrznych, na których arkusz też się otwiera", () => {
    // `client_interview` ma kartę i backend też pokazuje tam arkusz Championa,
    // ale to krok 07 („Rozmowy"), nie kolejka mojej rozmowy screeningowej.
    const ids = selectScreeningQueue(board).map((e) => e.item.candidate_id);
    expect(ids).not.toContain(141);
  });

  it("brak kolumny „Screening” w szablonie to pusta kolejka, nie wyjątek", () => {
    expect(selectScreeningQueue([board[1]])).toEqual([]);
  });
});

describe("selectPendingVerifications", () => {
  it("skanuje wszystkie kolumny nie-terminalne, nie tylko „Zweryfikowany”", () => {
    const pending = selectPendingVerifications(board);
    expect(pending.map((e) => e.item.id)).toEqual([22]);
  });

  it("pomija kolumny terminalne — odrzucony nie czeka już na akceptację", () => {
    const ids = selectPendingVerifications(board).map((e) => e.item.id);
    expect(ids).not.toContain(51);
  });
});

describe("selectVerifiedQueue", () => {
  it("zostawia w kolejce także karty czekające na akceptację stawki", () => {
    // Ukrycie ich zamieniłoby czekającą sprawę w niewidzialną — bramka ruchu
    // i tak je zatrzyma, ale rekruter ma je WIDZIEĆ.
    expect(selectVerifiedQueue(board).map((e) => e.item.id)).toEqual([21, 22]);
  });
});

describe("countAtClient", () => {
  it("liczy „CV Wysłane” i etapy zewnętrzne, pomija terminalne", () => {
    expect(countAtClient(board)).toBe(2);
  });
});

describe("moveBlockedReason", () => {
  it("brak prawa zapisu blokuje wszystko", () => {
    expect(moveBlockedReason({ item: item(), readOnly: true })).toContain(
      "Tylko do odczytu",
    );
  });

  it("weto hiring managera blokuje ruch nie-terminalny z powodem", () => {
    const reason = moveBlockedReason({
      item: item({
        hm_veto: {
          hiring_manager_contact_id: 5,
          source_job_id: 2,
          rejected_at: "2026-01-01",
          rejection_reason_name: "Brak doświadczenia w bankowości",
        },
      }),
      readOnly: false,
    });
    expect(reason).toContain("Brak doświadczenia w bankowości");
  });

  it("ruch TERMINALNY przechodzi mimo weta — inaczej kandydat utknąłby w procesie", () => {
    expect(
      moveBlockedReason({
        item: item({
          hm_veto: {
            hiring_manager_contact_id: 5,
            source_job_id: 2,
            rejected_at: "2026-01-01",
            rejection_reason_name: "Weto",
          },
        }),
        readOnly: false,
        terminal: true,
      }),
    ).toBeNull();
  });

  it("„pending” NIE jest bramką ruchu — backend też go tak nie traktuje", () => {
    expect(
      moveBlockedReason({
        item: item({ verification_status: "pending" }),
        readOnly: false,
      }),
    ).toBeNull();
  });
});

describe("itemFullName", () => {
  it("nie zostawia pustego napisu, gdy karta nie ma nazwiska", () => {
    expect(itemFullName(item({ name: undefined, lastname: undefined }))).toBe(
      "Kandydat",
    );
  });
});
