import { describe, expect, it } from "vitest";

import {
  contractActivityDetailRows,
  contractActivityLabel,
  contractDetailValue,
} from "@/components/contracts/contract-timeline-labels";

// UAT B23: zakładka Timeline kontraktu pokazywała `synced_with_orders`,
// `terminated`, `updated` i wieloliniowy JSON z `null`, `source_order_id`
// i identyfikatorem korekty `0307_…`.
describe("contract timeline labels", () => {
  it("tłumaczy slugi zdarzeń widoczne na osi czasu kontraktu", () => {
    expect(contractActivityLabel("synced_with_orders")).toBe(
      "Zsynchronizowano z zamówieniami klienta",
    );
    expect(contractActivityLabel("terminated")).toBe("Zakończono współpracę");
    expect(contractActivityLabel("updated")).toBe("Zaktualizowano dane kontraktu");
    expect(contractActivityLabel("end_date_cleared")).toMatch(/bezterminowa/);
    // „Powiąż z kontraktem” w rejestrze umów zostawia wpis na kontrakcie.
    expect(contractActivityLabel("generated_contract_linked")).toBe(
      "Powiązano podpisaną umowę B2B z kontraktem",
    );
  });

  it("nieznany slug nigdy nie wraca dosłownie", () => {
    expect(contractActivityLabel("some_future_action")).toBe("Zdarzenie systemowe");
    expect(contractActivityLabel(null)).toBe("Zdarzenie");
  });

  it("zamienia szczegóły synchronizacji na pary etykieta → wartość po polsku", () => {
    const rows = contractActivityDetailRows({
      source_order_id: 4242,
      rate_unit: { from: "hourly", to: "daily" },
      order_period_changed: true,
      revenue_steps_changed: [7, 9],
      client_order_end_date: "2026-12-31",
      previous_client_order_end_date: null,
    });
    const byKey = Object.fromEntries(rows.map((r) => [r.key, r]));

    expect(byKey.source_order_id.label).toBe("Zamówienie źródłowe");
    expect(byKey.source_order_id.value).toBe("#4242");
    expect(byKey.rate_unit.label).toBe("Jednostka stawki");
    expect(byKey.rate_unit.value).toBe("godzinowa → dzienna (MD)");
    expect(byKey.order_period_changed.value).toBe("tak");
    expect(byKey.revenue_steps_changed.value).toBe("#7, #9");
    expect(byKey.client_order_end_date.value).toBe("31.12.2026");
    expect(byKey.previous_client_order_end_date.value).toBe("—");
    // Żadna etykieta nie jest surowym kluczem z podkreśleniem.
    expect(rows.every((r) => !r.label.includes("_"))).toBe(true);
  });

  it("opisuje jednorazową korektę danych zamiast pokazywać jej identyfikator", () => {
    expect(contractDetailValue("source", "0307_b2b_indefinite_end_date")).toBe(
      "jednorazowa korekta danych (0307)",
    );
    expect(contractDetailValue("source", "daily_cost_sync")).toMatch(/dobowa/);
  });

  it("tłumaczy statusy, powody zakończenia i daty z czasem", () => {
    expect(contractDetailValue("from_status", "active")).toBe("Aktywny");
    expect(contractDetailValue("to_status", "ended")).toBe("Zakończony");
    expect(contractDetailValue("termination_reason", "project_ended")).toBe(
      "Koniec projektu",
    );
    expect(contractDetailValue("terminated_at", "2026-09-01T10:30:00")).toMatch(
      /^01\.09\.2026 \d{2}:\d{2}$/,
    );
    expect(contractDetailValue("early", false)).toBe("nie");
  });

  // Aneksy podpisane w Generatorze aneksów (0362) zapisują te klucze w
  // `new_values`; bez etykiet zakładka „Aneksy” pokazywała „legal name”
  // i surowe `sole_trader`.
  it("pola aneksów z Generatora aneksów mają etykiety i wartości po polsku", () => {
    const rows = contractActivityDetailRows({
      legal_name: "ZAJĄC IT Piotr Zając",
      nip: "5213900011",
      entity_type: "sole_trader",
      delegate_name: "Paweł Sowa",
      start_date_mode: "not_later",
      period_from: "2026-10-01",
      period_to: "2026-12-31",
      rate_changed: true,
    });
    const byKey = Object.fromEntries(rows.map((r) => [r.key, r]));

    expect(byKey.legal_name.label).toBe("Nazwa firmy");
    expect(byKey.nip.label).toBe("NIP");
    expect(byKey.entity_type.label).toBe("Forma działalności");
    expect(byKey.entity_type.value).toBe("JDG");
    expect(contractDetailValue("entity_type", "company")).toBe("spółka");
    expect(byKey.delegate_name.label).toBe("Osoba skierowana");
    expect(byKey.start_date_mode.label).toBe("Tryb daty rozpoczęcia");
    expect(byKey.start_date_mode.value).toBe("nie później niż");
    expect(byKey.period_from.label).toBe("Okres zlecenia od");
    expect(byKey.period_from.value).toBe("01.10.2026");
    expect(byKey.period_to.label).toBe("Okres zlecenia do");
    expect(byKey.rate_changed.label).toBe("Zmieniono stawkę");
    expect(byKey.rate_changed.value).toBe("tak");
  });

  it("nieznany klucz dostaje czytelną etykietę, a zagnieżdżony obiekt zwięzły JSON", () => {
    const [row] = contractActivityDetailRows({ some_new_key: { a: 1 } });
    expect(row.label).toBe("some new key");
    expect(row.value).toBe('{"a":1}');
  });
});
