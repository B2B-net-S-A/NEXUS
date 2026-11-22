/**
 * Oś zmian zakładki „Aneksy” (wariant A, 19.11.2026): identyczne zapisy
 * zwinięte, zmiana w jednej linii, węzły po dniu wejścia w życie.
 */
import { describe, expect, it } from "vitest";

import {
  amendmentAuthor,
  amendmentChangeLine,
  amendmentDuplicateKey,
  amendmentTitle,
  annexDocumentChangeLine,
  buildTimeline,
  duplicateNote,
  groupAmendments,
  timelineSummary,
  untilDay,
  type TimelineAmendment,
  type TimelineDocument,
} from "@/components/contracts/amendments/amendments-timeline";

/** Linia zmiany ma twardą spację przed jednostką — w oczekiwaniach piszemy zwykłą. */
const line = (...args: Parameters<typeof amendmentChangeLine>) => amendmentChangeLine(...args).replace(/\u00a0/g, " ");

const entry = (over: Partial<TimelineAmendment>): TimelineAmendment => ({
  id: 1,
  amendment_type: "rate_change",
  old_values: { rate_client: 180, rate_candidate: 140, status: "active", rate_unit: "hourly" },
  new_values: { rate_client: 170, rate_candidate: 130 },
  effective_date: "2026-07-01",
  reason: null,
  created_at: "2026-06-29T13:11:28Z",
  created_by_name: "Anna Przykładowa",
  created_by_email: null,
  source: "manual",
  state: "in_force",
  withdrawn: false,
  withdrawable: false,
  ...over,
});

// Ta sama zmiana stawek zapisana trzy razy (dwa razy 29.06, raz 05.07)
// i przedłużenie z tego samego dnia — kształt zgłoszenia z 19.11.2026.
const FIRST = entry({ id: 1, reason: "Klient obniżył stawkę od lipca." });
const SECOND = entry({ id: 3, created_at: "2026-06-29T13:21:26Z" });
const THIRD = entry({ id: 29, created_at: "2026-07-05T12:05:13Z", old_values: { rate_client: 180, rate_candidate: 140 } });
const EXTENSION = entry({
  id: 2,
  amendment_type: "extension",
  old_values: { status: "active", end_date: "2026-06-30" },
  new_values: { status: "active", end_date: "2026-12-31" },
  created_at: "2026-06-29T13:11:58Z",
});

describe("zwijanie identycznych zapisów", () => {
  it("ten sam rodzaj, dzień i nowe wartości to jedna zmiana; pierwszy zapis prowadzi", () => {
    const groups = groupAmendments([THIRD, SECOND, EXTENSION, FIRST]);
    expect(groups).toHaveLength(2);
    // W dniu: od najnowszego pierwszego zapisu — przedłużenie (13:11:58) nad stawkami (13:11:28).
    expect(groups.map((g) => g.main.id)).toEqual([2, 1]);
    const rates = groups[1];
    expect(rates.entries.map((e) => e.id)).toEqual([29, 3, 1]);
    expect(rates.reason).toBe("Klient obniżył stawkę od lipca.");
  });

  it("kolejność kluczy w nowych wartościach nie ma znaczenia, różny dzień albo kwota — tak", () => {
    const swapped = entry({ id: 5, new_values: { rate_candidate: 130, rate_client: 170 } });
    expect(amendmentDuplicateKey(swapped)).toBe(amendmentDuplicateKey(FIRST));
    expect(groupAmendments([FIRST, entry({ id: 6, effective_date: "2026-07-10" })])).toHaveLength(2);
    expect(groupAmendments([FIRST, entry({ id: 7, new_values: { rate_client: 171, rate_candidate: 130 } })])).toHaveLength(2);
  });

  it("wycofany wpis nie zwija się z niewycofanym — każdy ma swój stan", () => {
    const notice = entry({ id: 10, amendment_type: "early_termination", new_values: { end_date: "2026-10-31" } });
    const groups = groupAmendments([notice, { ...notice, id: 11, withdrawn: true }]);
    expect(groups).toHaveLength(2);
    expect(groups.map((g) => g.main.withdrawn)).toEqual([true, false]);
  });

  it("powód z generatora (składa go serwer) nie jest uzasadnieniem", () => {
    const generated = entry({ id: 12, source: "generator", reason: "Aneks — zmiana stawki z dnia 28.06.2026 (dokument #3)" });
    expect(groupAmendments([generated])[0].reason).toBeNull();
  });

  it("pusta lista to pusta oś", () => {
    expect(groupAmendments([])).toEqual([]);
    expect(buildTimeline([], [], "2026-11-20")).toEqual([]);
  });

  it("ostrzeżenie podaje liczbę zapisów i ich dni w kalendarzu firmy", () => {
    const [, rates] = groupAmendments([THIRD, SECOND, EXTENSION, FIRST]);
    expect(duplicateNote(rates.entries)).toBe("zapisano 3 razy (05.07, 29.06, 29.06) — możliwy duplikat");
    // 23:30 UTC to już następny dzień w Warszawie.
    expect(duplicateNote([{ created_at: "2026-06-29T23:30:00Z" }, { created_at: "2026-06-29T10:00:00Z" }])).toBe(
      "zapisano 2 razy (30.06, 29.06) — możliwy duplikat",
    );
  });
});

describe("zmiana w jednej linii", () => {
  it("stawki klienta i kandydata z jednostką kontraktu", () => {
    expect(line(FIRST)).toBe("klient 180,00 → 170,00 zł/h · kandydat 140,00 → 130,00 zł/h");
    expect(
      line(entry({ old_values: { rate_client: 900 }, new_values: { rate_client: 950.125 } }), {
        clientCurrency: "EUR",
        rateUnit: "daily",
      }),
    ).toBe("klient 900,00 → 950,125 EUR/MD");
    expect(line(entry({ old_values: {}, new_values: { rate_candidate: "100.5" } }))).toBe(
      "kandydat 100,50 zł/h",
    );
  });

  it("przedłużenie: koniec projektu, status bez zmiany nie wchodzi", () => {
    expect(line(EXTENSION)).toBe("koniec projektu 30.06.2026 → 31.12.2026");
  });

  it("wypowiedzenie skraca umowę, a wycofanie wraca do umowy bezterminowej bez pól technicznych", () => {
    const notice = entry({
      amendment_type: "early_termination",
      old_values: { end_date: "2026-12-15", status: "active" },
      new_values: { end_date: "2026-10-31", status: "ended" },
    });
    expect(line(notice)).toBe(
      "koniec projektu 15.12.2026 → 31.10.2026 (wcześniej niż było) · status aktywny → zakończony",
    );
    const withdrawal = entry({
      amendment_type: "custom_change",
      old_values: { end_date: "2026-10-31", status: "ended" },
      new_values: { annex_title: "Wycofanie wypowiedzenia", end_date: null, status: "active", withdrawn_amendment_id: 63 },
    });
    const text = line(withdrawal);
    expect(text).toBe("koniec projektu 31.10.2026 → bezterminowo · status zakończony → aktywny");
    expect(text).not.toMatch(/annex_title|withdrawn_amendment_id/);
  });

  it("pozostałe pola po polsku: projekt, NIP zostaje wielkimi literami, pole tak/nie", () => {
    expect(
      line(
        entry({ amendment_type: "scope_change", old_values: { project_name: "Migracja" }, new_values: { project_name: "Hurtownia danych" } }),
      ),
    ).toBe("projekt Migracja → Hurtownia danych");
    expect(
      line(entry({ amendment_type: "party_data_change", old_values: {}, new_values: { legal_name: "TESTOWY IT", nip: "0000000011" } })),
    ).toBe("nazwa firmy TESTOWY IT · NIP 0000000011");
    expect(line(entry({ amendment_type: "mandate_change", old_values: {}, new_values: { rate_changed: true } }))).toBe(
      "zmieniono stawkę",
    );
    expect(line(entry({ amendment_type: "typ_z_przyszlosci", old_values: null, new_values: {} }))).toBe("");
  });

  it("tytuł mówi, czyja stawka się zmieniła; aneks z własną nazwą ma swoją nazwę", () => {
    expect(amendmentTitle(FIRST)).toBe("Zmiana stawek");
    expect(amendmentTitle(entry({ new_values: { rate_client: 1 } }))).toBe("Zmiana stawki klienta");
    expect(amendmentTitle(entry({ new_values: { rate_candidate: 1 } }))).toBe("Zmiana stawki kandydata");
    expect(amendmentTitle(entry({ amendment_type: "custom_change", new_values: { annex_title: " Zwolnienie z zakazu " } }))).toBe(
      "Zwolnienie z zakazu",
    );
    expect(amendmentTitle(entry({ amendment_type: "typ_z_przyszlosci", new_values: {} }))).toBe("Aneks");
  });

  it("autor to imię i nazwisko, nigdy adres e-mail", () => {
    expect(amendmentAuthor({ created_by_name: null, created_by_email: "jan.testowy@example.com" })).toBe("Jan Testowy");
    expect(amendmentAuthor({ created_by_name: "Anna Przykładowa", created_by_email: "a@example.com" })).toBe("Anna Przykładowa");
    expect(amendmentAuthor({ created_by_name: null, created_by_email: null })).toBeNull();
  });

  it("aneks z generatora: czyja zmiana i przed → po", () => {
    expect(
      annexDocumentChangeLine({
        kind: "rate",
        hidden: false,
        currency: "PLN",
        items: [{ rate: 150, from: null, to: null }],
        before: [{ rate: 140, from: null, to: null }],
      }),
    ).toBe("kandydat 140,00 → 150,00 zł/h");
    expect(annexDocumentChangeLine({ kind: "start_date", before: "2026-11-02", after: "2026-11-16" })).toBe(
      "data startu 02.11.2026 → 16.11.2026",
    );
    expect(annexDocumentChangeLine({ kind: "rate", hidden: true })).toBeNull();
  });
});

describe("węzły osi", () => {
  const doc = (over: Partial<TimelineDocument & { id: number }>) => ({
    id: 1,
    effective_date: "2026-12-01",
    state: "waiting" as const,
    change: null,
    ...over,
  });

  it("od najnowszego dnia; aneks bez daty na górze; czekający przed zmianami, anulowany po nich", () => {
    const groups = groupAmendments([FIRST, EXTENSION, entry({ id: 40, effective_date: "2026-09-01", new_values: { rate_candidate: 120 } })]);
    const nodes = buildTimeline(
      groups,
      [doc({ id: 7, effective_date: null }), doc({ id: 8, effective_date: "2026-07-01", state: "cancelled" }), doc({ id: 9, effective_date: "2026-07-01" })],
      "2026-11-20",
    );
    expect(nodes.map((n) => n.date)).toEqual([null, "2026-09-01", "2026-07-01"]);
    const july = nodes[2];
    expect(july.waiting.map((d) => d.id)).toEqual([9]);
    expect(july.groups).toHaveLength(2);
    expect(july.documents.map((d) => d.id)).toEqual([8]);
  });

  it("„obowiązuje” to ostatni dzień ≤ dziś z niewycofaną zmianą; przyszły dzień ma flagę", () => {
    const notice = entry({ id: 50, amendment_type: "early_termination", effective_date: "2026-11-17", withdrawn: true, new_values: { end_date: "2026-10-31" } });
    const future = entry({ id: 51, effective_date: "2026-12-01", state: "signed_pending" });
    const nodes = buildTimeline(groupAmendments([FIRST, notice, future]), [], "2026-11-20");
    expect(nodes.map((n) => [n.date, n.future, n.current])).toEqual([
      ["2026-12-01", true, false],
      ["2026-11-17", false, false],
      ["2026-07-01", false, true],
    ]);
  });

  it("nagłówek osi liczy zmiany, czekające aneksy i powtórzenia z odmianą", () => {
    expect(timelineSummary(2, 0, 2)).toBe("2 zmiany · 2 powtórzone wpisy");
    expect(timelineSummary(1, 1, 0)).toBe("1 zmiana · 1 aneks czeka na podpis");
    expect(timelineSummary(5, 2, 1)).toBe("5 zmian · 2 aneksy czekają na podpis · 1 powtórzony wpis");
    expect(timelineSummary(0, 0, 0)).toBe("");
  });

  it("dzień wejścia w życie względem dziś", () => {
    expect(untilDay("2026-12-01", "2026-11-20")).toBe("za 11 dni");
    expect(untilDay("2026-11-21", "2026-11-20")).toBe("jutro");
  });
});
