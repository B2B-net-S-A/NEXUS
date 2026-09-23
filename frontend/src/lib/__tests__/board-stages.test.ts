import { describe, expect, it } from "vitest";

import cases from "@/lib/__fixtures__/board-stage-cases.json";
import {
  BOARD_COLUMN_ORDER,
  foldBoardColumns,
  isCproStageName,
  impliedBadges,
  isDzStageName,
  placeStage,
} from "@/lib/board-stages";

describe("etap szablonu → kolumna Tablicy + odznaka (prawdziwe nazwy z trzech szablonów)", () => {
  it.each(cases.cases)("$name → $column / $badge", (c) => {
    expect(placeStage({ label: c.name, stage: c.stage, category: c.category })).toEqual({
      column: c.column,
      badge: c.badge,
    });
  });

  it("reguła DZ i Cpro rozpoznaje tylko swoje etapy", () => {
    expect(isDzStageName("Przepuszczony przez DZ")).toBe(true);
    expect(isDzStageName("Zweryfikowany")).toBe(false);
    expect(isCproStageName("NORDEA: Wysłać do Cpro")).toBe(true);
    expect(isCproStageName("CV Wysłane")).toBe(false);
  });

  it("Tablica ma 6 kolumn, bez etapów w środku (decyzja 23.09.2026)", () => {
    expect(BOARD_COLUMN_ORDER).toEqual([
      "new",
      "verified",
      "cv_sent",
      "client_interview",
      "contract",
      "hired",
    ]);
  });
});

function col(label: string, stage: string, ids: number[], category = "internal") {
  return { label, stage, category, items: ids.map((id) => ({ id })), count: ids.length };
}

describe("foldBoardColumns", () => {
  const template = [
    col("Ogłoszenia", "posting", []),
    col("Nowi / Analiza CV", "new", [1]),
    col("Screening", "screening", []),
    col("Zweryfikowany", "verified", [2]),
    col("Przepuszczony przez DZ", "interview", [3]),
    col("Wysłać do Cpro", "new", [4]),
    col("CV Wysłane", "cv_sent", []),
    col("Preparation Meeting", "new", [5]),
    col("Interview Klient", "client_interview", [6], "external"),
    col("Akceptacja", "acceptance", [], "external"),
    col("Umowa wysłana", "new", [7], "external"),
    col("Umowa podpisana", "new", [8], "external"),
    col("Zatrudniony", "hired", [], "terminal"),
    col("Onboarding", "onboarding", [9], "external"),
    col("Odrzucony", "rejected", [10], "terminal"),
    col("Wycofany", "withdrawn", [], "terminal"),
  ];
  const folded = foldBoardColumns(template);

  it("„Default B2B”: 16 etapów → 6 kolumn + pasek zamkniętych", () => {
    expect(folded.columns.map((c) => c.label)).toEqual([
      "Nowi",
      "Zweryfikowany",
      "CV wysłane",
      "Rozmowa u klienta",
      "Umowa",
      "Zatrudniony",
    ]);
    expect(folded.columns.map((c) => c.key)).toEqual(BOARD_COLUMN_ORDER);
    expect(folded.closed.map((c) => c.label)).toEqual(["Odrzucony", "Wycofany"]);
  });

  it("u Nordei „CV wysłane” nazywa się „Wysłane do Cpro” — ta sama kolumna", () => {
    const nordea = foldBoardColumns(template, { cproEnabled: true });
    const sent = nordea.columns.find((c) => c.key === "cv_sent")!;
    expect(sent.label).toBe("Wysłane do Cpro");
    expect(nordea.columns.map((c) => c.key)).toEqual(BOARD_COLUMN_ORDER);
  });

  it("kolumna-host to etap bez odznaki; karty z etapów-odznak są w tej samej kolumnie", () => {
    const verified = folded.columns.find((c) => c.key === "verified")!;
    expect(verified.host.label).toBe("Zweryfikowany");
    expect(verified.items.map((i) => i.id)).toEqual([2, 3, 4]);
    expect(verified.count).toBe(3);
    const contract = folded.columns.find((c) => c.key === "contract")!;
    expect(contract.host.label).toBe("Akceptacja");
    expect(contract.items.map((i) => i.id)).toEqual([7, 8]);
    const nowi = folded.columns.find((c) => c.key === "new")!;
    expect(nowi.host.label).toBe("Nowi / Analiza CV");
    expect(nowi.members.map((m) => m.label)).toEqual([
      "Nowi / Analiza CV",
      "Ogłoszenia",
      "Screening",
    ]);
    const hired = folded.columns.find((c) => c.key === "hired")!;
    expect(hired.host.label).toBe("Zatrudniony");
    expect(hired.items.map((i) => i.id)).toEqual([9]);
  });

  it("odznaka jedzie z karty, nie z kolumny", () => {
    expect(folded.badgeByItemId.get(3)).toBe("dz");
    expect(folded.badgeByItemId.get(4)).toBe("cpro");
    expect(folded.badgeByItemId.get(5)).toBe("prep");
    expect(folded.badgeByItemId.get(8)).toBe("contract_signed");
    expect(folded.badgeByItemId.get(2)).toBeUndefined();
  });

  it("szablon z samych własnych etapów (kod `new`) NIE składa się w jedną kolumnę", () => {
    const custom = foldBoardColumns([
      col("Nowy", "new", [1]),
      col("Wstępny akcept", "new", [2]),
      col("Rozmowa telefoniczna", "new", [3]),
      col("Spotkanie", "new", []),
      col("Oferta", "new", []),
      col("Zatrudniony", "hired", [], "terminal"),
      col("Odrzucony", "rejected", [], "terminal"),
      col("Lista rezerwowa", "new", [4]),
    ]);
    expect(custom.columns.map((c) => c.label)).toEqual([
      "Nowi",
      "Wstępny akcept",
      "Rozmowa telefoniczna",
      "Spotkanie",
      "Oferta",
      "Zatrudniony",
    ]);
    expect(custom.closed.map((c) => c.label)).toEqual(["Odrzucony", "Lista rezerwowa"]);
  });

  it("szablon z Traffita: duplikaty „Zaakceptowany (#41)” łączą się, prep-y idą do rozmowy", () => {
    const traffit = foldBoardColumns([
      col("Nowy", "new", []),
      col("Screening", "screening", []),
      col("Kandydat Zweryfikowany", "verified", []),
      col("Przepuszczony przez DZ", "new", [1]),
      col("NORDEA: Wysłać do Cpro", "new", [2]),
      col("Wysłany do Klienta", "cv_sent", []),
      col("Interview - Prep", "new", [3]),
      col("Prep - Followup", "new", []),
      col("Interview u klienta", "client_interview", [], "external"),
      col("Po Interview", "new", [4], "external"),
      col("Zaakceptowany", "acceptance", [5], "external"),
      col("Zaakceptowany (#41)", "acceptance", [6], "external"),
      col("Zaakceptowany (#26)", "acceptance", [], "external"),
      col("Zatrudniony", "hired", [], "terminal"),
      col("Odrzucony", "rejected", [], "terminal"),
      col("Współpraca zakończona", "new", [], "terminal"),
      col("Ogłoszenia", "posting", []),
    ]);
    expect(traffit.columns.map((c) => c.label)).toEqual([
      "Nowi",
      "Zweryfikowany",
      "CV wysłane",
      "Rozmowa u klienta",
      "Umowa",
      "Zatrudniony",
    ]);
    const accept = traffit.columns.find((c) => c.key === "contract")!;
    expect(accept.items.map((i) => i.id)).toEqual([5, 6]);
    expect(traffit.badgeByItemId.get(5)).toBe("acceptance");
    const interview = traffit.columns.find((c) => c.key === "client_interview")!;
    expect(interview.items.map((i) => i.id)).toEqual([3, 4]);
    expect(traffit.closed).toHaveLength(2);
  });
});

describe("impliedBadges", () => {
  it("Cpro stoi po DZ w procesie — karta niesie obie odznaki", () => {
    expect(impliedBadges("cpro")).toEqual(["dz", "cpro"]);
    expect(impliedBadges("dz")).toEqual(["dz"]);
    expect(impliedBadges(null)).toEqual([]);
  });
});
