import { describe, expect, it } from "vitest";

import { plural } from "@/components/v2/jobs/SimilarJobsDialog";
import { reassignReason } from "@/lib/proposals-merge";
import {
  REQUEST_STATUS_FILTER_ORDER,
  REQUEST_STATUS_META,
  requestStatusOf,
} from "@/lib/request-status";
import {
  defaultSelection,
  selectedSentCount,
  type SimilarJobItem,
} from "@/lib/similar-jobs-api";

function item(id: number, sent: number): SimilarJobItem {
  return {
    id,
    title: `Rekrutacja ${id}`,
    reference_number: null,
    status: "published",
    closed_at: null,
    client_name: null,
    similarity: 80,
    sent_count: sent,
    linked: false,
  };
}

describe("podobne rekrutacje (0341)", () => {
  it("domyślnie zaznacza tylko sugestie z osobami wysłanymi do klienta", () => {
    expect(defaultSelection([item(1, 3), item(2, 0), item(3, 1)])).toEqual([1, 3]);
  });

  it("liczy osoby do przepięcia z zaznaczonych rekrutacji", () => {
    expect(selectedSentCount([item(1, 3), item(2, 5)], new Set([2]))).toBe(5);
  });

  it("odmienia „osoba” po polsku", () => {
    expect([1, 2, 5, 12, 22, 25].map(plural)).toEqual([
      "osobę",
      "osoby",
      "osób",
      "osób",
      "osoby",
      "osób",
    ]);
  });

  it("powód przepięcia mówi, gdzie i kiedy osoba była u klienta", () => {
    expect(
      reassignReason({
        job_id: 9,
        title: "Senior Java Developer",
        reference_number: "#4812",
        client_name: "PKO BP",
        stage: "cv_sent",
        sent_at: "2026-08-26",
      }),
    ).toBe("Wysłany do klienta: PKO BP · Senior Java Developer · 26.08.2026");
  });
});

describe("status requestu", () => {
  it("zna wszystkie wartości serwera i odrzuca nieznane", () => {
    for (const s of ["closed", "filled", "contract", "champion", "incomplete", "searching"]) {
      expect(requestStatusOf(s)).toBe(s);
    }
    expect(requestStatusOf("nope")).toBeNull();
    expect(requestStatusOf(undefined)).toBeNull();
  });

  it("filtr nie oferuje „Zamkniętej” (ma własną zakładkę), każda pozycja ma etykietę", () => {
    expect(REQUEST_STATUS_FILTER_ORDER).not.toContain("closed");
    expect(REQUEST_STATUS_META.champion.label).toBe("Mamy championa");
  });
});
