import { describe, expect, it } from "vitest";

import {
  diffSentence,
  groupHistory,
  groupTitle,
  humanizeActivity,
  personFromEmail,
  type ContractActivity,
} from "@/lib/contract-history";

const act = (over: Partial<ContractActivity>): ContractActivity => ({
  id: 1,
  action: "updated",
  details: null,
  user_name: "jan.kowalski@firma.pl",
  created_at: "2026-09-29T16:50:00Z",
  ...over,
});

describe("historia kontraktu po ludzku", () => {
  it("dokument z importu: nazwa pliku i rodzaj zamiast „via / doc type / size bytes”", () => {
    const e = humanizeActivity(
      act({
        action: "document_uploaded",
        details: { via: "sharepoint_import", doc_type: "annex", filename: "aneks.pdf", size_bytes: 268955 },
      }),
    );
    expect(e.title).toBe("Dodano dokument „aneks.pdf”");
    expect(e.detail).toBe("aneks · z SharePointa");
    expect(e.kind).toBe("documents");
    expect(e.who).toBe("Jan Kowalski");
  });

  it("aneks: tylko pola, które się zmieniły, bez JSON-a", () => {
    const e = humanizeActivity(
      act({
        action: "amendment_rate_change",
        details: {
          old: { status: "active", rate_client: 175, rate_candidate: 135, end_date: "2026-12-31" },
          new: { rate_client: 163, rate_candidate: 125 },
        },
      }),
    );
    expect(e.kind).toBe("money");
    expect(e.detail).toBe("stawka klienta 175,00 → 163,00 · stawka kandydata 135,00 → 125,00");
    expect(e.detail).not.toContain("{");
  });

  it("zdarzenie z migracji albo synchronizacji jest automatyczne", () => {
    expect(humanizeActivity(act({ action: "synced_with_orders", user_name: null })).automatic).toBe(true);
    expect(
      humanizeActivity(act({ action: "start_date_corrected", details: { source: "0334_contract_start_date_correction" } }))
        .automatic,
    ).toBe(true);
    expect(humanizeActivity(act({ action: "updated" })).automatic).toBe(false);
  });

  it("zapis bez zmian nie udaje zmiany", () => {
    expect(diffSentence({ rate_client: 163 }, { rate_client: 163 })).toBeNull();
    expect(diffSentence(undefined, undefined)).toBeNull();
  });

  it("seria tej samej osoby tego samego dnia zwija się do jednej grupy", () => {
    const events = [1, 2, 3].map((id) =>
      humanizeActivity(act({ id, action: "document_uploaded", details: { filename: `${id}.pdf` } })),
    );
    const other = humanizeActivity(act({ id: 4, action: "document_uploaded", created_at: "2026-09-28T10:00:00Z" }));
    const groups = groupHistory([...events, other]);
    expect(groups).toHaveLength(2);
    expect(groupTitle(groups[0])).toBe("Dodano 3 dokumenty");
    expect(groupTitle(groups[1])).toBe(other.title);
  });

  it("odmiana w tytule grupy: 5 i 12 dokumentów, 22 dokumenty", () => {
    const make = (n: number) =>
      groupHistory(
        Array.from({ length: n }, (_, i) => humanizeActivity(act({ id: i, action: "document_uploaded" }))),
      )[0];
    expect(groupTitle(make(5))).toBe("Dodano 5 dokumentów");
    expect(groupTitle(make(12))).toBe("Dodano 12 dokumentów");
    expect(groupTitle(make(22))).toBe("Dodano 22 dokumenty");
  });

  it("adres e-mail zamienia się w imię i nazwisko, brak autora to NEXUS", () => {
    expect(personFromEmail("anna.nowak-kowalska@firma.pl")).toBe("Anna Nowak Kowalska");
    expect(personFromEmail(null)).toBeNull();
  });
});
