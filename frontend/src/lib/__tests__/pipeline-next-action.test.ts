/**
 * „Następna akcja" na karcie i druga linia nagłówka kolumny (krok 04
 * Pipeline, fala 3 „parytet z makietami").
 */

import { describe, expect, it } from "vitest";

import {
  NO_NEXT_ACTION_LABEL,
  columnSlaHint,
  hasNoNextAction,
  nextActionFor,
  oldestDaysInColumn,
} from "@/lib/pipeline-next-action";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";

function item(overrides: Partial<KanbanItem> = {}): KanbanItem {
  return {
    id: 1,
    candidate_id: 100,
    stage: "new",
    name: "Jan",
    lastname: "Kowalski",
    days_in_stage: 3,
    ...overrides,
  };
}

function col(overrides: Partial<KanbanColumn> = {}): KanbanColumn {
  const items = overrides.items ?? [];
  return {
    stage: "new",
    name: "Nowi / Analiza CV",
    category: "internal",
    count: items.length,
    items,
    ...overrides,
  };
}

const intakeCol = col();
const screeningCol = col({ stage: "screening", name: "Screening" });
const verifiedCol = col({ stage: "verified", name: "Zweryfikowany" });
const cvSentCol = col({ stage: "cv_sent", name: "CV Wysłane" });
const clientInterviewCol = col({
  stage: "client_interview",
  name: "Interview Klient",
  category: "external",
});
const acceptanceCol = col({
  stage: "acceptance",
  name: "Akceptacja",
  category: "external",
});
const contractSentCol = col({
  stage: "new",
  name: "Umowa wysłana",
  category: "external",
});
const hiredCol = col({
  stage: "new",
  name: "Zatrudniony",
  category: "terminal",
  terminal_type: "hired",
});
const rejectedCol = col({
  stage: "new",
  name: "Odrzucony",
  category: "terminal",
  terminal_type: "rejected",
});

describe("nextActionFor — bramki wygrywają z etapem", () => {
  it("etap terminalny nie ma następnej akcji — karta nie renderuje wiersza", () => {
    const action = nextActionFor(item({ days_in_stage: 40 }), rejectedCol);
    expect(action.kind).toBe("none");
    expect(action.label).toBe("");
  });

  it("odrzucony z wetem HM nadal nie ma akcji (terminal przed bramką)", () => {
    const action = nextActionFor(
      item({
        hm_veto: {
          hiring_manager_contact_id: 1,
          source_job_id: 2,
          rejected_at: "2026-08-01T00:00:00Z",
          rejection_reason_name: "Nie pasuje",
        },
      }),
      rejectedCol,
    );
    expect(action.kind).toBe("none");
  });

  it("„pending” mówi o cudzej decyzji, nie o własnej akcji", () => {
    const action = nextActionFor(
      item({ verification_status: "pending" }),
      verifiedCol,
    );
    expect(action).toEqual({
      label: "Czeka na akceptację stawki",
      tone: "gate",
      kind: "verification",
    });
  });

  it("weto hiring managera blokuje etap nie-terminalny", () => {
    const action = nextActionFor(
      item({
        hm_veto: {
          hiring_manager_contact_id: 1,
          source_job_id: 2,
          rejected_at: "2026-08-01T00:00:00Z",
          rejection_reason_name: "Nie pasuje",
        },
      }),
      intakeCol,
    );
    expect(action.label).toBe("Bramka: weto HM");
    expect(action.tone).toBe("gate");
  });

  it("„pending” wygrywa z wetem — czekamy na decyzję, nie na ruch", () => {
    const action = nextActionFor(
      item({
        verification_status: "pending",
        hm_veto: {
          hiring_manager_contact_id: 1,
          source_job_id: 2,
          rejected_at: "2026-08-01T00:00:00Z",
          rejection_reason_name: "Nie pasuje",
        },
      }),
      verifiedCol,
    );
    expect(action.label).toBe("Czeka na akceptację stawki");
  });
});

describe("nextActionFor — etapy wejściowe", () => {
  it("świeża karta idzie do analizy CV", () => {
    expect(nextActionFor(item({ days_in_stage: 0 }), intakeCol)).toEqual({
      label: "Analiza CV · dziś",
      tone: "normal",
      kind: "analysis",
    });
    expect(nextActionFor(item({ days_in_stage: 1 }), intakeCol).label).toBe(
      "Analiza CV · dziś",
    );
  });

  it("od drugiego dnia karta prosi o screening", () => {
    for (const days of [2, 4, 6]) {
      expect(nextActionFor(item({ days_in_stage: days }), intakeCol).label).toBe(
        "Umów screening",
      );
    }
  });

  it("tydzień bez ruchu = brak następnej akcji, w tonie zaległości", () => {
    const action = nextActionFor(item({ days_in_stage: 7 }), intakeCol);
    expect(action.label).toBe(NO_NEXT_ACTION_LABEL);
    expect(action.tone).toBe("due");
    expect(hasNoNextAction(action)).toBe(true);
    expect(hasNoNextAction(nextActionFor(item({ days_in_stage: 2 }), intakeCol))).toBe(
      false,
    );
  });

  it("brak `days_in_stage` liczy się jak zero, nie jak zaległość", () => {
    expect(
      nextActionFor(item({ days_in_stage: undefined }), intakeCol).label,
    ).toBe("Analiza CV · dziś");
  });
});

describe("nextActionFor — screening i SLA klienta", () => {
  it("bez SLA zaległość zaczyna się po tygodniu", () => {
    expect(nextActionFor(item({ days_in_stage: 6 }), screeningCol).tone).toBe(
      "normal",
    );
    expect(nextActionFor(item({ days_in_stage: 7 }), screeningCol).tone).toBe("due");
  });

  it("SLA klienta krótsze niż tydzień przyspiesza zaległość", () => {
    const ctx = { slaDays: 5 };
    expect(nextActionFor(item({ days_in_stage: 4 }), screeningCol, ctx).tone).toBe(
      "normal",
    );
    expect(nextActionFor(item({ days_in_stage: 5 }), screeningCol, ctx).tone).toBe(
      "due",
    );
  });

  it("treść nie zależy od SLA — zmienia się tylko ton", () => {
    expect(
      nextActionFor(item({ days_in_stage: 9 }), screeningCol, { slaDays: 5 }).label,
    ).toBe("Uzupełnij arkusz screeningu");
  });
});

describe("nextActionFor — dalsze etapy", () => {
  it("po weryfikacji następnym krokiem jest CV do klienta", () => {
    expect(nextActionFor(item(), verifiedCol)).toEqual({
      label: "Wyślij CV do klienta",
      tone: "normal",
      kind: "cv",
    });
  });

  it("własny etap wewnętrzny PO screeningu dostaje grupę z tablicy", () => {
    const custom = col({ stage: "new", name: "Przepuszczony przez DZ" });
    // Bez grupy moduł nie odróżni go od etapu wejściowego…
    expect(nextActionFor(item(), custom).label).toBe("Umów screening");
    // …a z grupą policzoną nad całą tablicą — odróżni.
    expect(
      nextActionFor(item(), custom, { group: "verification" }).label,
    ).toBe("Wyślij CV do klienta");
  });

  it("etapy u klienta mówią, na czyj ruch czekamy", () => {
    expect(nextActionFor(item(), cvSentCol).label).toBe(
      "Umów interview / feedback klienta",
    );
    expect(nextActionFor(item(), clientInterviewCol).label).toBe(
      "Zbierz feedback HM",
    );
    expect(nextActionFor(item(), acceptanceCol).label).toBe(
      "Reakcja kandydata na ofertę",
    );
    expect(nextActionFor(item(), acceptanceCol).kind).toBe("offer");
  });

  it("własny etap zewnętrzny mówi tylko tyle, ile wiadomo", () => {
    const prep = col({
      stage: "new",
      name: "Preparation Meeting",
      category: "external",
    });
    expect(nextActionFor(item(), prep).label).toBe("Feedback klienta");
  });

  it("umowa: podpis, a po zatrudnieniu przekazanie do Delivery", () => {
    expect(nextActionFor(item(), contractSentCol).label).toBe("Podpis umowy");
    expect(nextActionFor(item(), hiredCol).label).toBe("Przekaż do Delivery");
    expect(
      nextActionFor(item(), col({ stage: "onboarding", name: "Onboarding" })).label,
    ).toBe("Przekaż do Delivery");
  });
});

describe("columnSlaHint", () => {
  it("kolumna screeningu z SLA pokazuje, ile dni zostało", () => {
    expect(
      columnSlaHint(screeningCol, { slaDays: 5, oldestDays: 3 }),
    ).toEqual({ left: "SLA klienta: 5 d", right: "2 d zostało", rightTone: "warn" });
  });

  it("przekroczone SLA mówi „po terminie”, nie ujemną liczbę dni", () => {
    const hint = columnSlaHint(screeningCol, { slaDays: 5, oldestDays: 9 });
    expect(hint.right).toBe("po terminie");
    expect(hint.rightTone).toBe("bad");
  });

  it("dokładnie na granicy SLA jest już po terminie", () => {
    expect(columnSlaHint(screeningCol, { slaDays: 5, oldestDays: 5 }).right).toBe(
      "po terminie",
    );
  });

  it("pusta kolumna screeningu nie liczy zaległości nikomu", () => {
    expect(columnSlaHint(screeningCol, { slaDays: 5, oldestDays: null })).toEqual({
      left: "SLA klienta: 5 d",
      right: null,
      rightTone: "normal",
    });
  });

  it("bez SLA screening zachowuje się jak każda inna kolumna", () => {
    expect(columnSlaHint(screeningCol, { oldestDays: 8 })).toEqual({
      left: "SLA: —",
      right: "najstarszy 8 d",
      rightTone: "warn",
    });
  });

  it("kolumna wejściowa mówi wprost, że nikt tu nie mierzy SLA", () => {
    expect(columnSlaHint(intakeCol, { slaDays: 5, oldestDays: 6 })).toEqual({
      left: "SLA: —",
      right: "najstarszy 6 d",
      rightTone: "normal",
    });
  });

  it("weryfikacja wskazuje następny krok, terminal — dok z powodami", () => {
    expect(columnSlaHint(verifiedCol, { oldestDays: 2 }).left).toBe(
      "→ CV do klienta",
    );
    expect(columnSlaHint(rejectedCol, { oldestDays: 90 })).toEqual({
      left: "powody w doku",
      right: null,
      rightTone: "normal",
    });
  });
});

describe("oldestDaysInColumn", () => {
  it("bierze maksimum i ignoruje karty bez wieku", () => {
    const populated = col({
      items: [
        item({ id: 1, days_in_stage: 2 }),
        item({ id: 2, days_in_stage: undefined }),
        item({ id: 3, days_in_stage: 11 }),
      ],
    });
    expect(oldestDaysInColumn(populated)).toBe(11);
  });

  it("pusta kolumna (i kolumna bez wieku) zwraca null, nie zero", () => {
    expect(oldestDaysInColumn(col())).toBeNull();
    expect(
      oldestDaysInColumn(col({ items: [item({ days_in_stage: undefined })] })),
    ).toBeNull();
  });
});

describe("nextActionFor — zatrudniony z zaległą bramką (follow-up fali 3)", () => {
  it("zatrudniony z zaległym `pending` dostaje „Przekaż do Delivery”, nie bramkę stawki", () => {
    const action = nextActionFor(
      item({ verification_status: "pending" }),
      hiredCol,
    );
    expect(action).toEqual({
      label: "Przekaż do Delivery",
      tone: "normal",
      kind: "contract",
    });
  });

  it("zatrudniony ze starym wetem HM też dostaje „Przekaż do Delivery”", () => {
    const action = nextActionFor(
      item({
        hm_veto: {
          hiring_manager_contact_id: 1,
          source_job_id: 2,
          rejected_at: "2026-09-01T10:00:00Z",
          rejection_reason_name: "Brak dopasowania",
        },
      }),
      hiredCol,
    );
    expect(action.label).toBe("Przekaż do Delivery");
    expect(action.tone).toBe("normal");
  });
});
