import { describe, expect, it } from "vitest";

import type { AnnexChangeRow } from "@/lib/api/b2bDocuments";
import {
  annexChangeLead,
  annexChangesProblems,
  annexChangeRows,
  CLAUSE_GAP,
  clauseRows,
  fillClauseText,
  MAX_ANNEX_CHANGE_TEXT,
  MAX_ANNEX_CHANGES,
} from "@/lib/annex-changes";
import {
  diffSentence,
  groupHistory,
  groupTitle,
  humanizeActivity,
  personFromEmail,
  type ContractActivity,
  type HistoryEvent,
} from "@/lib/contract-history";

function activity(overrides: Partial<ContractActivity>): ContractActivity {
  return {
    id: 1,
    action: "updated",
    details: null,
    user_name: "anna.przykladowa@firma-testowa.pl",
    created_at: "2026-12-31T10:00:00Z",
    ...overrides,
  };
}

describe("personFromEmail", () => {
  it("pusta wartość i null dają null", () => {
    expect(personFromEmail("")).toBeNull();
    expect(personFromEmail(null)).toBeNull();
    expect(personFromEmail(undefined)).toBeNull();
  });
  it("wartość bez „@” zostaje jak jest", () => {
    expect(personFromEmail("Jan Testowy")).toBe("Jan Testowy");
  });
  it("kropki, myślniki i podkreślenia rozdzielają człony", () => {
    expect(personFromEmail("jan_testowy-nowy@firma-testowa.pl")).toBe("Jan Testowy Nowy");
  });
});

describe("diffSentence — wartości brzegowe", () => {
  it("brak nowych danych albo nie-obiekt: null", () => {
    expect(diffSentence({}, null)).toBeNull();
    expect(diffSentence({}, "tekst")).toBeNull();
  });
  it("brak starych danych: lewa strona to kreska; daty po polsku", () => {
    expect(diffSentence(null, { end_date: "2027-01-01" })).toBe("koniec projektu — → 01.01.2027");
  });
  it("granica roku w dacie końca i zmiana stawki z groszami", () => {
    expect(
      diffSentence(
        { end_date: "2026-12-31T00:00:00", rate_client: 100.005 },
        { end_date: "2027-01-01", rate_client: 0 },
      ),
    ).toBe("koniec projektu 31.12.2026 → 01.01.2027 · stawka klienta 100,01 → 0,00");
  });
  it("pusty napis to kreska, napis bez formatu zostaje", () => {
    expect(diffSentence({ team_name: "" }, { team_name: "Zespół Testowy" })).toBe(
      "zespół — → Zespół Testowy",
    );
  });
  it("tylko nieznane albo niezmienione pola: null", () => {
    expect(diffSentence({ status: "active" }, { status: "active", foo: 1 })).toBeNull();
  });
});

describe("humanizeActivity", () => {
  it("usunięcie dokumentu z SharePointa przez człowieka", () => {
    const e = humanizeActivity(
      activity({
        action: "document_deleted",
        details: { doc_type: "annex", filename: "aneks.pdf", via: "sharepoint_import" },
      }),
    );
    expect(e).toMatchObject({
      kind: "documents",
      automatic: false,
      title: "Usunięto dokument „aneks.pdf”",
      detail: "aneks · z SharePointa",
      who: "Anna Przykladowa",
    });
  });

  it("dokument bez typu i bez nazwy: pusta nazwa i brak szczegółu", () => {
    const e = humanizeActivity(activity({ action: "document_uploaded", details: {} }));
    expect(e.title).toBe("Dodano dokument „”");
    expect(e.detail).toBeNull();
  });

  it("dokument dodany przez migrację jest automatyczny", () => {
    const e = humanizeActivity(
      activity({ action: "document_uploaded", details: { source: "0612_backfill", filename: "u.pdf" } }),
    );
    expect(e.kind).toBe("automatic");
    expect(e.automatic).toBe(true);
  });

  it("aneks bez autora: automatyczny, z opisem różnicy", () => {
    const e = humanizeActivity(
      activity({
        action: "amendment_rate_change",
        user_name: null,
        details: { old: { rate_candidate: 100 }, new: { rate_candidate: 110 } },
      }),
    );
    expect(e.kind).toBe("automatic");
    expect(e.who).toBeNull();
    expect(e.detail).toBe("stawka kandydata 100,00 → 110,00");
  });

  it("zmiana z synchronizacji (source z „sync”) jest automatyczna", () => {
    const e = humanizeActivity(
      activity({ action: "updated", details: { source: "orders_sync", old: {}, new: {} } }),
    );
    expect(e.kind).toBe("automatic");
    expect(e.detail).toBeNull();
  });

  it("inny aneks człowieka trafia do „Stawki”, z najwyżej trzema szczegółami bez technicznych pól", () => {
    const e = humanizeActivity(
      activity({
        action: "amendment_early_termination",
        details: {
          source: "ui",
          via: "x",
          size_bytes: 10,
          effective_date: "2026-12-31",
          end_date: "2027-01-01",
          business_day: true,
          margin: 12,
          empty: null,
        },
      }),
    );
    expect(e.kind).toBe("money");
    expect(e.title).toBe("Aneks: zakończenie wcześniej");
    const parts = (e.detail ?? "").split(" · ");
    expect(parts).toHaveLength(3);
    expect(e.detail).not.toMatch(/Źródło|size/);
    expect(parts[0]).toMatch(/^Obowiązuje od: /);
  });

  it("zdarzenie bez szczegółów: detail null, rodzaj „contract”", () => {
    const e = humanizeActivity(activity({ action: "terminated", details: null }));
    expect(e.kind).toBe("contract");
    expect(e.detail).toBeNull();
  });

  it("zdarzenie automatyczne z listy akcji mimo autora", () => {
    expect(humanizeActivity(activity({ action: "synced_with_orders" })).kind).toBe("automatic");
  });
});

function ev(id: number, action: string, at: string, who: string | null = "Jan Testowy"): HistoryEvent {
  return { id, at, who, automatic: false, kind: "documents", title: `T${id}`, detail: null, action };
}

describe("groupHistory i groupTitle", () => {
  it("pusta lista", () => {
    expect(groupHistory([])).toEqual([]);
  });

  it("ten sam dzień i osoba, ale granica dnia/roku rozdziela grupy", () => {
    const groups = groupHistory([
      ev(1, "document_uploaded", "2026-12-31T23:00:00"),
      ev(2, "document_uploaded", "2026-12-31T23:30:00"),
      ev(3, "document_uploaded", "2027-01-01T00:10:00"),
      ev(4, "document_uploaded", "2027-01-01T00:20:00", null),
    ]);
    expect(groups.map((g) => g.events.map((e) => e.id))).toEqual([[1, 2], [3], [4]]);
  });

  it("usunięcia: 2 dokumenty, 5 dokumentów, 12 dokumentów", () => {
    const del = (n: number) => ({
      key: "k",
      events: Array.from({ length: n }, (_, i) => ev(i, "document_deleted", "2026-12-31")),
    });
    expect(groupTitle(del(2))).toBe("Usunięto 2 dokumenty");
    expect(groupTitle(del(5))).toBe("Usunięto 5 dokumentów");
    expect(groupTitle(del(12))).toBe("Usunięto 12 dokumentów");
    expect(groupTitle(del(1))).toBe("T0");
  });

  it("inna seria: tytuł z krotnością", () => {
    const g = { key: "k", events: [ev(1, "updated", "2026-12-31"), ev(2, "updated", "2026-12-31")] };
    expect(groupTitle(g)).toBe("T1 (2×)");
  });
});

const row = (r: Partial<AnnexChangeRow>): AnnexChangeRow => ({
  op: "replace",
  paragraph: "5",
  section: "",
  text: "Nowa treść",
  ...r,
});

describe("annexChangeRows / annexChangesProblems — ścieżki odmowy", () => {
  it("nie-tablica i elementy bez „op” odpadają", () => {
    expect(annexChangeRows(null)).toEqual([]);
    expect(annexChangeRows({ op: "add" })).toEqual([]);
    expect(annexChangeRows([null, 1, { x: 1 }, row({})])).toHaveLength(1);
  });

  it("ponad limit zmian", () => {
    const rows = Array.from({ length: MAX_ANNEX_CHANGES + 1 }, () => row({}));
    expect(annexChangesProblems(rows)).toEqual([`Aneks mieści najwyżej ${MAX_ANNEX_CHANGES} zmian.`]);
  });

  it("dokładnie limit zmian przechodzi", () => {
    expect(annexChangesProblems(Array.from({ length: MAX_ANNEX_CHANGES }, () => row({})))).toEqual([]);
  });

  it("za długi numer paragrafu albo ustępu", () => {
    expect(annexChangesProblems([row({ paragraph: "1234567890123" })])).toEqual([
      "Zmiana 1: numer paragrafu albo ustępu jest za długi.",
    ]);
    expect(annexChangesProblems([row({ op: "add", section: "1234567890123" })])).toEqual([
      "Zmiana 1: numer paragrafu albo ustępu jest za długi.",
    ]);
  });

  it("treść ponad limit znaków; dokładnie limit przechodzi", () => {
    expect(annexChangesProblems([row({ text: "x".repeat(MAX_ANNEX_CHANGE_TEXT + 1) })])).toEqual([
      `Zmiana 1: treść ma więcej niż ${MAX_ANNEX_CHANGE_TEXT} znaków.`,
    ]);
    expect(annexChangesProblems([row({ text: "x".repeat(MAX_ANNEX_CHANGE_TEXT) })])).toEqual([]);
  });

  it("skreślenie bez treści i własny tekst bez paragrafu są poprawne", () => {
    expect(annexChangesProblems([row({ op: "delete", text: "" })])).toEqual([]);
    expect(annexChangesProblems([row({ op: "free", paragraph: "" })])).toEqual([]);
  });

  it("dodanie bez ustępu, bez paragrafu i z niewypełnioną luką", () => {
    expect(annexChangesProblems([row({ op: "add", paragraph: "", text: `x ${CLAUSE_GAP}` })])).toEqual([
      "Zmiana 1: podaj numer paragrafu (§).",
      "Zmiana 1: podaj numer dodawanego ustępu.",
      `Zmiana 1: uzupełnij miejsca oznaczone ${CLAUSE_GAP}.`,
    ]);
  });
});

describe("annexChangeLead", () => {
  it("nowe brzmienie bez paragrafu i z ustępem", () => {
    expect(annexChangeLead(row({ paragraph: "§ " }))).toBe("§ … Umowy otrzymuje brzmienie: „…”");
    expect(annexChangeLead(row({ paragraph: "§7", section: " 2 " }))).toBe(
      "§ 7 ust. 2 Umowy otrzymuje brzmienie: „…”",
    );
  });
  it("dodanie bez paragrafu i ustępu: wielokropki", () => {
    expect(annexChangeLead(row({ op: "add", paragraph: "", section: "" }))).toBe(
      "w § … Umowy dodaje się ust. … w brzmieniu: „…”",
    );
  });
  it("skreślenie i własny tekst", () => {
    expect(annexChangeLead(row({ op: "delete", paragraph: "3" }))).toBe("§ 3 Umowy skreśla się.");
    expect(annexChangeLead(row({ op: "free" }))).toBe("punkt aneksu z Twoją treścią");
  });
});

describe("fillClauseText / clauseRows", () => {
  it("brakująca albo pusta wartość zostaje luką; nazwa z kropką bez podwójnej kropki", () => {
    expect(
      fillClauseText("Klient {client_legal_name}. Paragraf {p}. Inne {q}", {
        client_legal_name: "Firma Testowa S.A.",
        p: "  ",
      }),
    ).toBe(`Klient Firma Testowa S.A. Paragraf ${CLAUSE_GAP}. Inne ${CLAUSE_GAP}`);
  });

  it("wiersze klauzuli bez paragrafu i ustępu dostają puste napisy", () => {
    expect(
      clauseRows(
        { key: "k", label: "L", title: "T", rows: [{ op: "free", text: "Zakaz {x}" }] },
        { x: "konkurencji" },
      ),
    ).toEqual([{ op: "free", paragraph: "", section: "", text: "Zakaz konkurencji" }]);
  });
});
