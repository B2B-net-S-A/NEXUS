/**
 * Kolejki kroków 05 i 06 oraz bramka ruchu (program „flow w języku C2", PR 6/7).
 */

import { describe, expect, it } from "vitest";

import {
  bulkMoveFailureMessage,
  HM_VETO_ENFORCED_STAGES,
  PIPELINE_GROUP_LABEL,
  countAtClient,
  countContractSent,
  countContractStages,
  countExternal,
  countHired,
  countHmVeto,
  countInProcess,
  countInterviewStages,
  countStage,
  countStalled,
  findStageColumn,
  groupKanbanColumns,
  groupKeyForColumn,
  formatExpectedRate,
  itemFullName,
  moveBlockedReason,
  primaryForwardMove,
  selectOverBudget,
  selectScreeningQueue,
  selectVerifiedQueue,
  stageAgeTone,
} from "@/lib/pipeline-flow";
import {
  colId,
  type KanbanColumn,
  type KanbanItem,
} from "@/components/v2/pages/kanban-shared";

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
        expected_rate_value: 200,
        expected_rate_unit: "hourly",
        expected_rate_currency: "PLN",
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
        expected_rate_value: 200,
        expected_rate_unit: "hourly",
        expected_rate_currency: "PLN",
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

describe("selectOverBudget", () => {
  it("porównuje stawkę z AKTUALNYM budżetem PLN/h, na kolumnach nie-terminalnych", () => {
    const over = selectOverBudget(board, 150);
    expect(over.map((e) => e.item.id)).toEqual([22]);
  });

  it("pomija kolumny terminalne", () => {
    const ids = selectOverBudget(board, 150).map((e) => e.item.id);
    expect(ids).not.toContain(51);
  });

  it("stawka w budżecie albo brak budżetu PLN/h = nikt nie jest ponad budżet", () => {
    expect(selectOverBudget(board, 250)).toEqual([]);
    expect(selectOverBudget(board, null)).toEqual([]);
  });
});

describe("selectVerifiedQueue", () => {
  it("zawiera wszystkie karty z „Zweryfikowany” (także stare z `pending`)", () => {
    expect(selectVerifiedQueue(board).map((e) => e.item.id)).toEqual([21, 22]);
  });
});

describe("countAtClient", () => {
  it("liczy „CV Wysłane” i etapy zewnętrzne, pomija terminalne", () => {
    expect(countAtClient(board)).toBe(2);
  });
});

/**
 * Selektory klastra KPI jobbara (fala „parytet z makietami").
 *
 * Wszystkie liczą przez `col.count`, czyli tę samą liczbę, którą listwa kroków
 * pokazuje tuż nad jobbarem — dwie różne liczby pod tą samą nazwą na jednym
 * ekranie byłyby gorsze niż brak którejkolwiek.
 */
describe("selektory KPI", () => {
  it("countInProcess pomija kolumny terminalne", () => {
    // 2 screening + 2 verified + 1 cv_sent + 1 client_interview = 6;
    // „Odrzucony" (terminal) jest poza procesem.
    expect(countInProcess(board)).toBe(6);
  });

  it("countExternal jest WĘŻSZE niż countAtClient — cv_sent to nie „u klienta”", () => {
    expect(countExternal(board)).toBe(1);
    expect(countAtClient(board)).toBe(2);
  });

  it("countStalled liczy tylko karty nie-terminalne powyżej progu", () => {
    const stalled = [
      col({
        stage: "screening",
        items: [
          item({ id: 1, days_in_stage: 8 }),
          item({ id: 2, days_in_stage: 7 }),
          // Brak `days_in_stage` NIE liczy się jako zaległość — nie wiemy.
          item({ id: 3 }),
        ],
      }),
      col({
        stage: "rejected",
        category: "terminal",
        terminal_type: "rejected",
        items: [item({ id: 4, stage: "rejected", days_in_stage: 400 })],
      }),
    ];
    expect(countStalled(stalled, 7)).toBe(1);
  });

  it("countHmVeto pomija karty terminalne", () => {
    const veto = {
      hiring_manager_contact_id: 1,
      source_job_id: 2,
      rejected_at: "2026-09-01",
      rejection_reason_name: "Brak doświadczenia",
    };
    const withVeto = [
      col({ stage: "screening", items: [item({ id: 1, hm_veto: veto })] }),
      col({
        stage: "rejected",
        category: "terminal",
        terminal_type: "rejected",
        items: [item({ id: 2, stage: "rejected", hm_veto: veto })],
      }),
    ];
    expect(countHmVeto(withVeto)).toBe(1);
  });

  it("countStage czyta legacy-etap, a brak kolumny to zero, nie wyjątek", () => {
    expect(countStage(board, "cv_sent")).toBe(1);
    expect(countStage(board, "acceptance")).toBe(0);
  });

  it("countHired rozpoznaje terminal po `terminal_type`, nie po nazwie kolumny", () => {
    const hired = [
      // Kolumna spoza legacy-enuma raportuje `stage: "new"` — po nim
      // zatrudnionych rozpoznać się NIE DA.
      col({
        stage: "new",
        name: "Zatrudniony",
        category: "terminal",
        terminal_type: "hired",
        items: [item({ id: 1 }), item({ id: 2 })],
      }),
      ...board,
    ];
    expect(countHired(hired)).toBe(2);
    expect(countHired(board)).toBe(0);
  });

  it("countContractSent bierze „Umowa wysłana”, ale nie „Umowa podpisana”", () => {
    const contract = [
      col({ stage: "new", name: "Umowa wysłana", items: [item({ id: 1 })] }),
      col({ stage: "new", name: "Umowa podpisana", items: [item({ id: 2 })] }),
    ];
    expect(countContractSent(contract)).toBe(1);
    expect(countContractStages(contract)).toBe(2);
  });

  it("countInterviewStages i countContractStages nie zaliczają tej samej karty dwa razy", () => {
    const both = [
      col({
        stage: "client_interview",
        name: "Interview Klient",
        category: "external",
        items: [item({ id: 1, stage: "client_interview" })],
      }),
      col({
        stage: "new",
        name: "Umowa wysłana",
        category: "external",
        items: [item({ id: 2 })],
      }),
    ];
    expect(countInterviewStages(both)).toBe(1);
    expect(countContractStages(both)).toBe(1);
  });
});

/**
 * Bramka ruchu = lustro `POST /api/pipeline/move`. Każdy przypadek niżej to
 * rozjazd, który istniał: UI wyszarzało „Zweryfikowany"/„Zatrudniony" przy
 * wecie (serwer je przepuszcza). Bramka „Pending" jest wyłączona od
 * 17.09.2026 — stawka ponad budżet nie blokuje żadnego ruchu.
 */
describe("moveBlockedReason", () => {
  const veto = {
    hiring_manager_contact_id: 5,
    source_job_id: 2,
    rejected_at: "2026-01-01",
    rejection_reason_name: "Brak doświadczenia w bankowości",
  };

  it("brak prawa zapisu blokuje wszystko", () => {
    expect(
      moveBlockedReason({ item: item(), readOnly: true, targetStage: "verified" }),
    ).toContain("Tylko do odczytu");
  });

  it.each(["cv_sent", "client_interview", "verified", "screening", "acceptance", "hired", "new"])(
    "weto hiring managera NIE blokuje „%s” — od 17.09.2026 to ostrzeżenie serwera",
    (targetStage) => {
      expect(
        moveBlockedReason({
          item: item({ hm_veto: veto }),
          readOnly: false,
          targetStage,
        }),
      ).toBeNull();
    },
  );

  it("zbiór etapów weta jest lustrem VETO_ENFORCED_STAGES z backendu", () => {
    expect([...HM_VETO_ENFORCED_STAGES].sort()).toEqual([
      "client_interview",
      "cv_sent",
    ]);
  });

  it("ruch WYPISUJĄCY przechodzi mimo weta — inaczej kandydat utknąłby w procesie", () => {
    expect(
      moveBlockedReason({
        item: item({ hm_veto: veto }),
        readOnly: false,
        terminal: true,
        targetStage: "rejected",
      }),
    ).toBeNull();
  });

  it("stara karta `pending` NIE blokuje ruchu — bramka zdjęta 17.09.2026", () => {
    const pending = item({ verification_status: "pending" });
    for (const targetStage of ["cv_sent", "verified", "hired"]) {
      expect(
        moveBlockedReason({ item: pending, readOnly: false, targetStage }),
      ).toBeNull();
    }
  });

  it("karta bez weta i bez „Pending” przechodzi", () => {
    expect(
      moveBlockedReason({ item: item(), readOnly: false, targetStage: "cv_sent" }),
    ).toBeNull();
  });
});

/**
 * Główna akcja „naprzód" doku. Od 17.09.2026 weto HM nie blokuje — dok
 * proponuje następny etap, a serwer ostrzega przy ruchu („Przenieś mimo to").
 */
describe("primaryForwardMove", () => {
  const veto = {
    hiring_manager_contact_id: 5,
    source_job_id: 2,
    rejected_at: "2026-01-01",
    rejection_reason_name: "Brak doświadczenia w bankowości",
  };

  function at(stageName: string, overrides: Partial<KanbanItem> = {}) {
    const columns = defaultB2B();
    const current = columns.find((c) => c.name === stageName);
    if (!current) throw new Error(`brak etapu ${stageName}`);
    return {
      columns,
      currentColId: colId(current),
      item: item({ stage: current.stage, ...overrides }),
    };
  }

  it("karta z wetem przed „CV Wysłane” dostaje „CV Wysłane” — weto jest ostrzeżeniem", () => {
    const { columns, currentColId, item: card } = at("Wysłać do Cpro", {
      hm_veto: veto,
    });
    const move = primaryForwardMove({
      item: card,
      columns,
      currentColId,
      readOnly: false,
    });
    expect(move.target?.name).toBe("CV Wysłane");
    expect(move.blocked).toBeNull();
  });

  it("karta bez weta idzie na następny etap — w tym „CV Wysłane”", () => {
    const { columns, currentColId, item: card } = at("Wysłać do Cpro");
    const move = primaryForwardMove({
      item: card,
      columns,
      currentColId,
      readOnly: false,
    });
    expect(move.target?.name).toBe("CV Wysłane");
    expect(move.blocked).toBeNull();
  });

  it("terminal po drodze jest pomijany — „Zatrudniony” nie jest krokiem naprzód z doku", () => {
    const { columns, currentColId, item: card } = at("Umowa podpisana");
    const move = primaryForwardMove({
      item: card,
      columns,
      currentColId,
      readOnly: false,
    });
    expect(move.target?.name).toBe("Onboarding");
  });

  it("brak prawa zapisu: żadnej akcji naprzód (jak dotąd)", () => {
    const readOnly = at("Wysłać do Cpro");
    expect(primaryForwardMove({ ...readOnly, readOnly: true })).toEqual({
      target: null,
      blocked: null,
    });
  });
});

describe("itemFullName", () => {
  it("nie zostawia pustego napisu, gdy karta nie ma nazwiska", () => {
    expect(itemFullName(item({ name: undefined, lastname: undefined }))).toBe(
      "Kandydat",
    );
  });
});

// ── Grupy etapów lewej kolumny (fala 3 „parytet z makietami") ───────────────

/** Pełny „Default B2B" z produkcji — piętnaście kolumn w kolejności szablonu. */
function defaultB2B(): KanbanColumn[] {
  const spec: Array<[string, string, KanbanColumn["category"], number]> = [
    ["new", "Nowi / Analiza CV", "internal", 13],
    ["screening", "Screening", "internal", 2],
    ["verified", "Zweryfikowany", "internal", 0],
    ["new", "Przepuszczony przez DZ", "internal", 0],
    ["new", "Wysłać do Cpro", "internal", 0],
    ["cv_sent", "CV Wysłane", "internal", 0],
    ["new", "Preparation Meeting", "external", 0],
    ["client_interview", "Interview Klient", "external", 0],
    ["acceptance", "Akceptacja", "external", 0],
    ["new", "Umowa wysłana", "external", 0],
    ["new", "Umowa podpisana", "external", 0],
    ["new", "Zatrudniony", "terminal", 0],
    ["onboarding", "Onboarding", "external", 0],
    ["new", "Odrzucony", "terminal", 9],
    ["new", "Wycofany", "terminal", 0],
  ];
  return spec.map(([stage, name, category, count], index) => ({
    stage,
    name,
    category,
    stage_def_id: 300 + index,
    count,
    items: Array.from({ length: count }, (_, i) =>
      item({ id: 1000 + index * 100 + i, candidate_id: 2000 + index * 100 + i }),
    ),
    terminal_type:
      name === "Zatrudniony"
        ? "hired"
        : name === "Odrzucony"
          ? "rejected"
          : name === "Wycofany"
            ? "withdrawn"
            : null,
  }));
}

describe("groupKanbanColumns — pełny „Default B2B”", () => {
  const groups = groupKanbanColumns(defaultB2B());
  const byKey = new Map(groups.map((g) => [g.key, g]));

  it("daje sześć grup w stałej kolejności", () => {
    expect(groups.map((g) => g.key)).toEqual([
      "intake",
      "screening",
      "verification",
      "client",
      "contract",
      "closed",
    ]);
  });

  it("liczy tyle, ile pokazuje makieta", () => {
    expect(byKey.get("intake")?.count).toBe(13);
    expect(byKey.get("screening")?.count).toBe(2);
    expect(byKey.get("verification")?.count).toBe(0);
    expect(byKey.get("client")?.count).toBe(0);
    expect(byKey.get("contract")?.count).toBe(0);
    expect(byKey.get("closed")?.count).toBe(9);
  });

  it("etapy wewnętrzne PO screeningu idą do weryfikacji, nie do wejścia", () => {
    expect(byKey.get("verification")?.columns.map((c) => c.name)).toEqual([
      "Zweryfikowany",
      "Przepuszczony przez DZ",
      "Wysłać do Cpro",
    ]);
    expect(byKey.get("intake")?.columns.map((c) => c.name)).toEqual([
      "Nowi / Analiza CV",
    ]);
  });

  it("„Zatrudniony” jest w umowie, nie wśród odrzuconych", () => {
    expect(byKey.get("contract")?.columns.map((c) => c.name)).toEqual([
      "Umowa wysłana",
      "Umowa podpisana",
      "Zatrudniony",
      "Onboarding",
    ]);
    expect(byKey.get("closed")?.columns.map((c) => c.name)).toEqual([
      "Odrzucony",
      "Wycofany",
    ]);
  });

  it("etapy u klienta to CV wysłane i wszystko zewnętrzne przed umową", () => {
    expect(byKey.get("client")?.columns.map((c) => c.name)).toEqual([
      "CV Wysłane",
      "Preparation Meeting",
      "Interview Klient",
      "Akceptacja",
    ]);
  });

  it("suma kolumn we wszystkich grupach = cała tablica (nic nie ginie)", () => {
    const grouped = groups.flatMap((g) => g.columns.map((c) => c.name));
    expect(grouped).toHaveLength(15);
    expect(new Set(grouped).size).toBe(15);
  });
});

describe("groupKanbanColumns — szablony niepełne", () => {
  it("szablon bez kolumny „Zweryfikowany” nadal ma grupę weryfikacji", () => {
    const columns = defaultB2B().filter((c) => c.name !== "Zweryfikowany");
    const byKey = new Map(groupKanbanColumns(columns).map((g) => [g.key, g]));
    expect(byKey.get("verification")?.columns.map((c) => c.name)).toEqual([
      "Przepuszczony przez DZ",
      "Wysłać do Cpro",
    ]);
  });

  it("brak etapów zewnętrznych = brak wiersza „U klienta” (nie wiersz z zerem)", () => {
    const columns = defaultB2B().filter(
      (c) => c.category !== "external" && c.stage !== "cv_sent",
    );
    const keys = groupKanbanColumns(columns).map((g) => g.key);
    expect(keys).not.toContain("client");
    expect(keys).toContain("intake");
  });

  it("same kolumny custom bez mapowania trafiają do jednej grupy", () => {
    // Szablon, w którym backend nie zmapował ŻADNEGO etapu na legacy enum —
    // wszystkie raportują `stage: "new"`. Bez screeningu nie ma po czym
    // przeciąć listy, więc powstaje jedna grupa; widok ma z tego wyciągnąć
    // wniosek „grupowanie nic nie wnosi” i pokazać płaską listę etapów.
    const columns: KanbanColumn[] = ["Etap A", "Etap B", "Etap C"].map(
      (name, index) => ({
        stage: "new",
        name,
        category: "internal",
        stage_def_id: 400 + index,
        count: index,
        items: [],
      }),
    );
    const groups = groupKanbanColumns(columns);
    expect(groups).toHaveLength(1);
    expect(groups[0].key).toBe("intake");
    expect(groups[0].count).toBe(0 + 1 + 2);
  });

  it("pusta tablica nie wymyśla żadnej grupy", () => {
    expect(groupKanbanColumns([])).toEqual([]);
  });
});

describe("groupKeyForColumn — bez znajomości reszty tablicy", () => {
  it("terminal bez `terminal_type` nadal jest zamknięciem, nie etapem procesu", () => {
    expect(
      groupKeyForColumn(
        col({ stage: "new", name: "Archiwum", category: "terminal" }),
      ),
    ).toBe("closed");
  });

  it("etykiety grup są jednym źródłem prawdy dla widoku", () => {
    expect(PIPELINE_GROUP_LABEL.closed).toBe("Odrzuceni / wycofani");
    expect(PIPELINE_GROUP_LABEL.client).toBe("U klienta (CV → interview)");
  });
});

describe("stageAgeTone", () => {
  it("brak wieku to `neutral`, nie „w porządku” — zielona kropka obiecywałaby wiedzę, której nie ma", () => {
    expect(stageAgeTone(undefined)).toBe("neutral");
    expect(stageAgeTone(null)).toBe("neutral");
  });

  it("bez SLA klienta trzyma progi z makiety: 7 dni to `bad`, 3 dni to `warn`", () => {
    expect(stageAgeTone(1)).toBe("ok");
    expect(stageAgeTone(3)).toBe("warn");
    expect(stageAgeTone(8)).toBe("bad");
  });

  it("z SLA klienta progi liczą się OD NIEGO, nie od stałej", () => {
    // SLA 5 dni: piątego dnia przekroczone, trzeciego (60 %) ostrzega.
    expect(stageAgeTone(5, 5)).toBe("bad");
    expect(stageAgeTone(3, 5)).toBe("warn");
    expect(stageAgeTone(2, 5)).toBe("ok");
    // Bez tego kandydat u klienta z 3-dniowym SLA byłby „ok" do siódmego dnia.
    expect(stageAgeTone(4, 3)).toBe("bad");
  });
});

describe("formatExpectedRate", () => {
  it("skraca jednostkę tak, jak mówi o niej rekruter", () => {
    expect(
      formatExpectedRate(
        item({ expected_rate_value: 118, expected_rate_unit: "hourly" }),
      ),
    ).toBe("118 PLN/h");
    // Backend zwraca `Numeric` jako string — obie postaci muszą dać to samo.
    expect(
      formatExpectedRate(
        item({ expected_rate_value: "544", expected_rate_unit: "daily" }),
      ),
    ).toBe("544 PLN/dzień");
    expect(
      formatExpectedRate(
        item({ expected_rate_value: 20000, expected_rate_unit: "monthly" }),
      ),
    ).toBe("20000 PLN/mc");
  });

  it("brak stawki to `null` — pusty napis udawałby zero", () => {
    expect(formatExpectedRate(item())).toBeNull();
    expect(formatExpectedRate(item({ expected_rate_value: null }))).toBeNull();
  });

  it("bez jednostki pokazuje walutę, zamiast zmyślać godziny", () => {
    expect(
      formatExpectedRate(
        item({ expected_rate_value: 118, expected_rate_currency: "EUR" }),
      ),
    ).toBe("118 EUR");
  });
});

describe("groupKanbanColumns — własny etap między etapami klienta (follow-up fali 3)", () => {
  it("„Preparation Meeting” oznaczony jako wewnętrzny, ale stojący za „CV Wysłane”, trafia do „U klienta”", () => {
    // Na prodzie ten etap szablonu „Default B2B" nie ma legacy enuma i jest
    // oznaczony jako wewnętrzny — po pozycji jest spotkaniem u klienta.
    const columns = defaultB2B().map((c) =>
      c.name === "Preparation Meeting" ? { ...c, category: "internal" as const } : c,
    );
    const groups = groupKanbanColumns(columns);
    const client = groups.find((g) => g.key === "client");
    const verification = groups.find((g) => g.key === "verification");
    expect(client?.columns.map((c) => c.name)).toEqual([
      "CV Wysłane",
      "Preparation Meeting",
      "Interview Klient",
      "Akceptacja",
    ]);
    expect(verification?.columns.map((c) => c.name)).toEqual([
      "Zweryfikowany",
      "Przepuszczony przez DZ",
      "Wysłać do Cpro",
    ]);
  });

  it("etap wewnętrzny PRZED pierwszym etapem klienta zostaje w weryfikacji", () => {
    const groups = groupKanbanColumns(defaultB2B());
    expect(groups.find((g) => g.key === "verification")?.columns.map((c) => c.name)).toEqual([
      "Zweryfikowany",
      "Przepuszczony przez DZ",
      "Wysłać do Cpro",
    ]);
  });
});


describe("groupKanbanColumns — „Ogłoszenia” (posting) przed „Nowi”", () => {
  const columns = defaultB2B();
  const posting: KanbanColumn = {
    ...columns[0],
    stage: "posting",
    name: "Ogłoszenia",
    stage_def_id: 299,
    count: 4,
    items: [],
    terminal_type: null,
  };
  const groups = groupKanbanColumns([posting, ...columns]);
  const byKey = new Map(groups.map((g) => [g.key, g]));

  it("dostaje własną grupę na początku, nie zlewa się z wejściem", () => {
    expect(groups.map((g) => g.key)[0]).toBe("posting");
    expect(byKey.get("posting")?.columns.map((c) => c.name)).toEqual(["Ogłoszenia"]);
    expect(byKey.get("posting")?.count).toBe(4);
    expect(byKey.get("intake")?.columns.map((c) => c.name)).toEqual(["Nowi / Analiza CV"]);
    expect(byKey.get("intake")?.count).toBe(13);
  });
});

describe("bulkMoveFailureMessage (REC-06)", () => {
  it("do 3 nazwisk z powodami, reszta jako „i N więcej”", () => {
    const failures = [1, 2, 3, 4, 5].map((n) => ({ name: `Osoba ${n}`, reason: `powód ${n}.` }));
    expect(bulkMoveFailureMessage(failures, 9)).toBe(
      "Nie udało się przenieść 5 z 9 kandydatów: Osoba 1 — powód 1; Osoba 2 — powód 2; Osoba 3 — powód 3 (i 2 więcej).",
    );
    expect(bulkMoveFailureMessage([{ name: "A", reason: "x" }], 2)).toBe(
      "Nie udało się przenieść 1 z 2 kandydatów: A — x.",
    );
  });
});
