import { describe, expect, it } from "vitest";

import {
  buildContractHappening,
  relativeDays,
  type HappeningContract,
  type HappeningCare,
} from "@/lib/contract-happening";

const TODAY = "2026-11-19";

const base: HappeningContract = {
  status: "active",
  contract_type: "b2b",
  end_date: null,
  terminated_at: null,
  termination_reason: null,
  termination_lessons: null,
  agreement_termination_mode: null,
  client_order_end_date: null,
  prolongation_status: "unknown",
  rate_client: 163,
  can_reverse_termination: false,
};

const careWatch: HappeningCare = {
  level: "watch",
  reasons: ["rozmowa zaległa 49 dni", "zamówienie kończy się za 42 dni, bez decyzji", "brak rozmowy od 353 dni"],
  ownerName: "Opiekun Testowy",
};

describe("„Co się dzieje” na stronie kontraktu", () => {
  it("spokojny kontrakt nie ma żadnej sprawy", () => {
    expect(buildContractHappening(base, null, TODAY)).toEqual([]);
  });

  it("umowa podpisana po starcie pracy daje ostrzeżenie z liczbą dni bez umowy", () => {
    const items = buildContractHappening(
      {
        ...base,
        date_warnings: [
          { code: "start_before_signature", start_date: "2026-11-02", day: "2026-11-10" },
        ],
      },
      null,
      TODAY,
    );
    expect(items).toEqual([
      expect.objectContaining({
        id: "dates",
        tone: "warning",
        lead: "Start przed podpisem — umowa podpisana 10.11.2026, praca od 02.11.2026",
        actions: [],
      }),
    ]);
    expect(items[0].detail).toContain("Przez 8 dni");
  });

  it("próg stawki sprzed startu mówi o dacie, bez kwoty", () => {
    const items = buildContractHappening(
      {
        ...base,
        date_warnings: [
          { code: "rate_step_before_start", start_date: "2026-11-16", day: "2026-06-01" },
        ],
      },
      null,
      TODAY,
    );
    expect(items).toHaveLength(1);
    expect(items[0].lead).toBe("Próg stawki od 01.06.2026 jest sprzed startu umowy (16.11.2026)");
    expect(items[0].detail).not.toMatch(/zł|PLN/);
  });

  it("zaplanowane zakończenie za 11 dni jest czerwone, z powodem i nierozwiązaną umową", () => {
    const items = buildContractHappening(
      {
        ...base,
        status: "ending",
        end_date: "2026-11-30",
        terminated_at: "2026-11-30",
        termination_reason: "client_budget_cut",
        termination_lessons: "no budget",
        can_reverse_termination: true,
      },
      null,
      TODAY,
    );
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({
      id: "end",
      tone: "danger",
      lead: "Współpraca kończy się 30.11.2026 — za 11 dni",
      actions: ["record_agreement", "reverse_termination"],
    });
    expect(items[0].detail).toContain("cięcie budżetu klienta");
    expect(items[0].detail).toContain("Umowa B2B nie jest rozwiązana");
  });

  it("rozwiązana umowa B2B nie podsuwa „Zapisz rozwiązanie”, a bez prawa cofnięcia nie ma „Cofnij”", () => {
    const items = buildContractHappening(
      { ...base, status: "ending", end_date: "2026-12-31", terminated_at: "2026-12-31", agreement_termination_mode: "notice" },
      null,
      TODAY,
    );
    expect(items[0].tone).toBe("warning");
    expect(items[0].actions).toEqual([]);
  });

  it("zakończona współpraca z nierozwiązaną umową B2B przypomina o porozumieniu", () => {
    const items = buildContractHappening(
      { ...base, status: "ended", end_date: "2026-10-31", terminated_at: "2026-10-31" },
      null,
      TODAY,
    );
    expect(items[0]).toMatchObject({ id: "end", actions: ["record_agreement"] });
    expect(items[0].lead).toContain("umowa B2B nie jest rozwiązana");
  });

  // Kontrakt #605 (22.11.2026): wypowiedzenie z SharePointa w Dokumentach,
  // rozwiązanie niezapisane — pas nie może mówić „nie jest rozwiązana”.
  const noticeDoc = {
    id: 9001,
    doc_type: "termination_notice" as const,
    filename: "Wypowiedzenie umowy.pdf",
    content_type: "application/pdf",
    source: "sharepoint_import",
    created_at: "2026-09-29T10:15:00Z",
  };

  it("zakończona współpraca z wypowiedzeniem w Dokumentach mówi o dokumencie, nie o nierozwiązanej umowie", () => {
    const items = buildContractHappening(
      { ...base, status: "ended", end_date: "2026-10-31", termination_document: noticeDoc },
      null,
      TODAY,
    );
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({
      id: "end",
      tone: "info",
      lead: "Współpraca zakończona 31.10.2026 — wypowiedzenie umowy B2B jest w Dokumentach, rozwiązanie niezapisane",
      actions: ["record_agreement"],
    });
    expect(items[0].lead).not.toContain("nie jest rozwiązana");
    expect(items[0].detail).toContain("„Wypowiedzenie umowy.pdf”, dodane 29.09.2026 z SharePointa");
    expect(items[0].detail).toContain("ostatnim dniem umowy");
  });

  it("porozumienie dodane ręcznie nie wspomina SharePointa", () => {
    const items = buildContractHappening(
      {
        ...base,
        status: "ended",
        end_date: "2026-10-31",
        termination_document: { ...noticeDoc, doc_type: "termination_agreement", source: null },
      },
      null,
      TODAY,
    );
    expect(items[0].lead).toContain("porozumienie umowy B2B jest w Dokumentach");
    expect(items[0].detail).not.toContain("SharePoint");
  });

  it("zaplanowane zakończenie z wypowiedzeniem w Dokumentach zastępuje zdanie o nierozwiązanej umowie", () => {
    const items = buildContractHappening(
      {
        ...base,
        status: "ending",
        end_date: "2026-11-30",
        terminated_at: "2026-11-30",
        termination_document: noticeDoc,
      },
      null,
      TODAY,
    );
    expect(items[0].detail).toContain("Wypowiedzenie umowy B2B jest w Dokumentach");
    expect(items[0].detail).not.toContain("nie jest rozwiązana");
    expect(items[0].actions).toContain("record_agreement");
  });

  it("dokument przy zapisanym rozwiązaniu niczego nie dokłada", () => {
    expect(
      buildContractHappening(
        {
          ...base,
          status: "ended",
          end_date: "2026-10-31",
          agreement_termination_mode: "notice",
          termination_document: noticeDoc,
        },
        null,
        TODAY,
      ),
    ).toEqual([]);
  });

  it("zakończona współpraca z rozwiązaną umową nic nie pokazuje", () => {
    expect(
      buildContractHappening(
        { ...base, status: "ended", end_date: "2026-10-31", agreement_termination_mode: "agreement" },
        null,
        TODAY,
      ),
    ).toEqual([]);
  });

  it("zamówienie w horyzoncie 60 dni pokazuje decyzję o przedłużeniu i akcje", () => {
    const items = buildContractHappening({ ...base, client_order_end_date: "2026-12-31", prolongation_status: "negotiate" }, null, TODAY);
    expect(items[0]).toMatchObject({
      id: "order_end",
      tone: "warning",
      lead: "Zamówienie kończy się 31.12.2026 — za 42 dni",
      detail: "Przedłużenie w negocjacjach.",
      actions: ["add_order", "terminate"],
    });
  });

  it("zamówienie dalej niż 60 dni albo już minione nie trafia na górę", () => {
    expect(buildContractHappening({ ...base, client_order_end_date: "2027-03-31" }, null, TODAY)).toEqual([]);
    expect(buildContractHappening({ ...base, client_order_end_date: "2026-10-31" }, null, TODAY)).toEqual([]);
  });

  it("opieka „Uwaga” nie powtarza końca zamówienia, który stoi wyżej", () => {
    const items = buildContractHappening({ ...base, client_order_end_date: "2026-12-31" }, careWatch, TODAY);
    expect(items.map((i) => i.id)).toEqual(["order_end", "care"]);
    expect(items[1].lead).toBe("Opieka: rozmowa zaległa 49 dni");
    expect(items[1].detail).toBe("Brak rozmowy od 353 dni · Opiekun: Opiekun Testowy");
    expect(items[1].detail).not.toContain("zamówienie kończy");
  });

  it("opieka „ok” i ryzyko „risk”: ok nic nie dodaje, risk jest czerwone", () => {
    expect(buildContractHappening(base, { ...careWatch, level: "ok" }, TODAY)).toEqual([]);
    const risk = buildContractHappening(base, { ...careWatch, level: "risk" }, TODAY);
    expect(risk[0]).toMatchObject({ id: "care", tone: "danger" });
  });

  it("osoba bez wglądu w kwoty nie dostaje „Brak stawki klienta” — serwer zeruje jej stawki", () => {
    expect(
      buildContractHappening({ ...base, rate_client: null }, null, TODAY, { canSeeRates: false }),
    ).toEqual([]);
  });

  it("brak stawki klienta tylko przy żywej umowie", () => {
    const rates = { canSeeRates: true };
    expect(buildContractHappening({ ...base, rate_client: null }, null, TODAY, rates)[0]).toMatchObject({
      id: "rate",
      actions: ["fill_rate"],
    });
    expect(buildContractHappening({ ...base, status: "draft", rate_client: null }, null, TODAY, rates)).toEqual([]);
  });
});

describe("„Klient zamówił okres po zakończeniu” (19.11.2026)", () => {
  const heldDraft = {
    order_id: 894,
    client_id: 12,
    order_group_id: null,
    order_number: "4500123456",
    status: "draft",
    start_date: "2026-12-01",
    end_date: "2027-05-31",
    held_by_termination: true,
  };

  it("szkic z maila po wypowiedzeniu: osobna pozycja z trzema wyjściami", () => {
    const items = buildContractHappening(
      {
        ...base,
        status: "ending",
        end_date: "2026-11-30",
        terminated_at: "2026-11-30",
        agreement_termination_mode: "agreement",
        can_reverse_termination: true,
        order_after_end: [heldDraft],
      },
      null,
      TODAY,
    );
    expect(items.map((item) => item.id)).toEqual(["end", "order_after_end"]);
    // „Cofnij zakończenie” stoi przy konflikcie, nie dwa razy.
    expect(items[0].actions).toEqual([]);
    expect(items[1]).toMatchObject({
      key: "order_after_end:894",
      tone: "danger",
      lead: "Klient zamówił okres po zakończeniu współpracy",
      actions: ["reverse_termination", "reassign_order", "cancel_order_draft"],
      order: heldDraft,
    });
    expect(items[1].detail).toBe(
      "Szkic zamówienia 4500123456: 01.12.2026 – 31.05.2027, a współpraca kończy się 30.11.2026. " +
        "NEXUS nie aktywuje go sam, bo zakończenie współpracy to decyzja człowieka.",
    );
  });

  it("aktywna linia na zakończonej umowie zlecenie: przedłużenie aneksem zamiast cofnięcia", () => {
    const items = buildContractHappening(
      {
        ...base,
        status: "ended",
        contract_type: "uzlecenie",
        end_date: "2026-10-31",
        can_reverse_termination: true,
        order_after_end: [
          {
            order_id: 951,
            client_id: 12,
            order_group_id: 108,
            order_number: "108/2026",
            status: "active",
            start_date: "2026-11-02",
            end_date: null,
            held_by_termination: false,
          },
        ],
      },
      null,
      TODAY,
    );
    expect(items).toHaveLength(1);
    expect(items[0].actions).toEqual(["extend_agreement", "reassign_order"]);
    expect(items[0].detail).toBe(
      "Linia zamówienia zbiorczego 108/2026: od 02.11.2026 bez daty końca, a współpraca " +
        "zakończyła się 31.10.2026. Umowa zlecenie nie przedłuża się zamówieniem — przedłuż ją " +
        "aneksem albo załóż nowy kontrakt.",
    );
  });

  it("bez zamówienia po końcu nic nie dochodzi, a żywy kontrakt pozycji nie dostaje", () => {
    const ending = {
      ...base,
      status: "ending",
      end_date: "2026-11-30",
      terminated_at: "2026-11-30",
      agreement_termination_mode: "agreement",
      can_reverse_termination: true,
    };
    const items = buildContractHappening({ ...ending, order_after_end: [] }, null, TODAY);
    expect(items.map((item) => item.id)).toEqual(["end"]);
    expect(items[0].actions).toEqual(["reverse_termination"]);
    expect(
      buildContractHappening({ ...base, order_after_end: [heldDraft] }, null, TODAY),
    ).toEqual([]);
  });
});

describe("dni po polsku", () => {
  it("dziś, jutro, za N dni, N dni temu", () => {
    expect(relativeDays(0)).toBe("dziś");
    expect(relativeDays(1)).toBe("jutro");
    expect(relativeDays(11)).toBe("za 11 dni");
    expect(relativeDays(-1)).toBe("wczoraj");
    expect(relativeDays(-5)).toBe("5 dni temu");
  });
});
