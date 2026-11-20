import { describe, expect, it } from "vitest";

import { contractPanelWarnings, lacksActiveOrder, type PanelContract } from "@/lib/contract-panel";

const TODAY = "2026-11-20";

const base: PanelContract = {
  status: "active",
  contract_type: "b2b",
  start_date: "2026-01-01",
  end_date: null,
  terminated_at: null,
  termination_reason: null,
  termination_lessons: null,
  agreement_termination_mode: null,
  client_order_start_date: "2026-01-01",
  client_order_end_date: "2027-06-30",
  prolongation_status: "unknown",
  rate_candidate: 120,
  rate_client: 170,
  can_reverse_termination: false,
  can_return_after_break: false,
};

const finance = { canViewFinance: true };

describe("ostrzeżenie panelu kontraktu (wariant A)", () => {
  it("spokojny kontrakt: nic", () => {
    expect(contractPanelWarnings(base, null, TODAY, finance)).toEqual([]);
  });

  it("zaplanowane odejście: jedna sprawa zamiast „zakończenie” + „zamówienie kończy się” o tym samym", () => {
    const items = contractPanelWarnings(
      {
        ...base,
        status: "ending",
        end_date: "2026-11-30",
        terminated_at: "2026-11-30",
        termination_reason: "project_ended",
        client_order_end_date: "2026-11-30",
      },
      null,
      TODAY,
      finance,
    );
    expect(items.map((i) => i.id)).toEqual(["end"]);
    expect(items[0]).toMatchObject({ tone: "danger", lead: "Współpraca kończy się 30.11.2026 — za 10 dni" });
    expect(items[0].actions).toContain("record_agreement");
  });

  it("brak aktywnego zamówienia stoi po odejściu, przed brakiem stawki", () => {
    const items = contractPanelWarnings(
      {
        ...base,
        status: "ending",
        end_date: "2026-12-31",
        terminated_at: "2026-12-31",
        agreement_termination_mode: "notice",
        client_order_start_date: null,
        client_order_end_date: null,
        rate_client: null,
      },
      null,
      TODAY,
      finance,
    );
    expect(items.map((i) => i.id)).toEqual(["end", "no_order", "rate"]);
    expect(items[1]).toMatchObject({
      tone: "danger",
      detail: "Kontrakt nie ma uzupełnionego zamówienia u klienta.",
      actions: ["add_order"],
    });
  });

  it("zamówienie skończone: brak aktywnego z datą ostatniego", () => {
    const [item] = contractPanelWarnings({ ...base, client_order_end_date: "2026-10-31" }, null, TODAY, finance);
    expect(item).toMatchObject({ id: "no_order", detail: "Ostatnie zamówienie skończyło się 31.10.2026." });
  });

  it("zamówienie w 60 dni: zdanie paska strony z przedłużeniem, bez drugiego „braku zamówienia”", () => {
    const items = contractPanelWarnings({ ...base, client_order_end_date: "2026-12-31", prolongation_status: "yes" }, null, TODAY, finance);
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ id: "order_end", detail: "Klient przedłuża.", actions: ["add_order", "terminate"] });
  });

  it("umowa z datą końca bez zapisanego zakończenia (np. zlecenie) dalej jest widoczna", () => {
    const [item] = contractPanelWarnings(
      { ...base, contract_type: "uzlecenie", status: "ending", end_date: "2026-12-10", client_order_end_date: "2027-06-30" },
      null,
      TODAY,
      finance,
    );
    expect(item).toMatchObject({ id: "contract_end", tone: "warning", lead: "Umowa kończy się 10.12.2026 — za 20 dni" });
  });

  it("zakończony: informacja z przywróceniem; z nierozwiązaną umową — zdanie paska i przywrócenie", () => {
    const ended = { ...base, status: "ended", end_date: "2026-08-31", terminated_at: "2026-08-31" };
    const withNotice = contractPanelWarnings({ ...ended, agreement_termination_mode: "notice" }, null, TODAY, finance);
    expect(withNotice).toEqual([
      { id: "ended", tone: "info", lead: "Kontrakt zakończony 31.08.2026", detail: null, actions: ["recover"] },
    ]);
    const open = contractPanelWarnings({ ...ended, can_reverse_termination: true }, null, TODAY, finance);
    expect(open).toHaveLength(1);
    expect(open[0].lead).toBe("Współpraca zakończona 31.08.2026 — umowa B2B nie jest rozwiązana");
    expect(open[0].actions).toEqual(["record_agreement", "recover"]);
  });

  it("szkic: braki tylko z tych pól, które konto widzi", () => {
    const draft = { ...base, status: "draft", start_date: null, rate_client: null };
    expect(contractPanelWarnings(draft, null, TODAY, finance)[0]).toMatchObject({
      id: "draft",
      lead: "Szkic — brakuje: data rozpoczęcia, stawka przychodowa",
      actions: ["complete_draft"],
    });
    expect(contractPanelWarnings(draft, null, TODAY, { canViewFinance: false })[0].lead).toBe(
      "Szkic — brakuje: data rozpoczęcia",
    );
    expect(contractPanelWarnings({ ...base, status: "draft" }, null, TODAY, finance)[0].lead).toBe(
      "Szkic — uzupełnij i aktywuj, żeby kontrakt zaczął obowiązywać",
    );
  });

  it("brak stawki klienta bez wglądu w kwoty to nie brak (serwer redaguje)", () => {
    expect(contractPanelWarnings({ ...base, rate_client: null }, null, TODAY, { canViewFinance: false })).toEqual([]);
  });

  it("brak aktywnego zamówienia dotyczy tylko trwającej współpracy", () => {
    const noOrder = { ...base, client_order_start_date: null, client_order_end_date: null };
    expect(lacksActiveOrder(noOrder, TODAY)).toBe(true);
    expect(lacksActiveOrder({ ...noOrder, status: "ended" }, TODAY)).toBe(false);
    expect(lacksActiveOrder({ ...noOrder, status: "draft" }, TODAY)).toBe(false);
  });
});
