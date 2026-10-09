import { describe, expect, it } from "vitest";

import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import {
  agreementBadge,
  agreementProjectDescription,
  daysSince,
  pairColumnLabel,
  prefillRateSource,
  type CardAgreement,
} from "@/lib/b2b-agreement";
import { cardBadges } from "@/lib/board-card-badges";

const NOW = new Date("2026-10-04T10:00:00Z");

function agreement(extra: Partial<CardAgreement> = {}): CardAgreement {
  return {
    id: 5,
    number: "1535/2026",
    contract_status: "in_progress",
    signature_status: "unsigned",
    created_at: "2026-10-02T09:00:00Z",
    signed_at: null,
    signature_requested_at: null,
    contract_id: null,
    ...extra,
  };
}

describe("plakietka umowy na karcie", () => {
  it("niepodpisana: dni czekania, od tygodnia ostrzeżenie", () => {
    expect(agreementBadge(agreement(), NOW)).toMatchObject({
      label: "Do podpisu · 2 d",
      tone: "info",
    });
    expect(
      agreementBadge(agreement({ created_at: "2026-09-26T09:00:00Z" }), NOW),
    ).toMatchObject({ label: "Do podpisu · 8 d", tone: "warning" });
    expect(
      agreementBadge(agreement({ created_at: "2026-10-04T09:00:00Z" }), NOW)?.label,
    ).toBe("Umowa wygenerowana");
  });

  it("prośba o podpis i podpisana", () => {
    expect(
      agreementBadge(
        agreement({ signature_requested_at: "2026-10-03T09:00:00Z" }),
        NOW,
      )?.label,
    ).toBe("Prośba o podpis");
    expect(
      agreementBadge(
        agreement({ signature_status: "signed_both", contract_status: "active" }),
        NOW,
      ),
    ).toMatchObject({ label: "Umowa podpisana", tone: "success" });
  });

  it("anulowana, zakończona i brak umowy — bez plakietki", () => {
    expect(agreementBadge(agreement({ contract_status: "cancelled" }), NOW)).toBeNull();
    expect(agreementBadge(agreement({ contract_status: "closed" }), NOW)).toBeNull();
    expect(agreementBadge(null, NOW)).toBeNull();
  });

  it("karta pokazuje umowę w każdej kolumnie, także przed „Umową”", () => {
    const item = {
      id: 1,
      candidate_id: 11,
      stage: "client_interview",
      agreement: agreement(),
    } as KanbanItem;
    const badges = cardBadges(item, {
      column: "client_interview",
      cproEnabled: false,
      viewerId: 7,
      now: NOW,
    });
    expect(badges.find((b) => b.key === "agreement")).toMatchObject({
      label: "Do podpisu · 2 d",
      tone: "info",
    });
  });
});

describe("podpisy i etykiety", () => {
  it("źródło stawki z datą", () => {
    expect(
      prefillRateSource({ value: 140, source: "card", at: "2026-10-01T08:00:00Z" }),
    ).toBe("ze screeningu · 01.10.2026");
    expect(prefillRateSource({ value: 140, source: "rate_from", at: null })).toBe(
      "„Stawka od” kandydata",
    );
    expect(prefillRateSource(null)).toBeNull();
  });

  it("kolumna pary w rejestrze", () => {
    expect(pairColumnLabel("contract")).toBe("Umowa");
    expect(pairColumnLabel("closed")).toBe("Zamknięci");
    expect(pairColumnLabel("unknown")).toBeNull();
    expect(pairColumnLabel(null)).toBeNull();
  });

  it("dni od daty", () => {
    expect(daysSince("2026-10-01T10:00:00Z", NOW)).toBe(3);
    expect(daysSince("2026-10-09T10:00:00Z", NOW)).toBe(0);
    expect(daysSince("zła data", NOW)).toBeNull();
  });
});

describe("agreementProjectDescription", () => {
  const MAIL =
    "Dzień dobry, szukamy testera. Stawka do 150 zł/h netto B2B. Pozdrawiam, Jan";

  it("bierze ogłoszenie z rekrutacji z Traffita", () => {
    expect(
      agreementProjectDescription({
        external_source: "traffit",
        description: "Projekt bankowy, zespół 6 osób.",
        champion_profile: { project: { about: "Inny opis" } },
      }),
    ).toBe("Projekt bankowy, zespół 6 osób.");
  });

  it("bierze opis projektu z Championa dla rekrutacji z NEXUSA", () => {
    expect(
      agreementProjectDescription({
        external_source: "manual",
        description: MAIL,
        champion_profile: { project: { about: "  System płatności.  " } },
      }),
    ).toBe("System płatności.");
  });

  it("czyta stary kształt profilu", () => {
    expect(
      agreementProjectDescription({
        external_source: null,
        description: MAIL,
        champion_profile: { project_context: { about: "Migracja danych." } },
      }),
    ).toBe("Migracja danych.");
  });

  it("bez opisu w Championie zwraca null — nigdy surowego maila klienta", () => {
    expect(
      agreementProjectDescription({ external_source: "manual", description: MAIL }),
    ).toBeNull();
    expect(
      agreementProjectDescription({
        external_source: "manual",
        description: MAIL,
        champion_profile: { project: { about: "   " } },
      }),
    ).toBeNull();
  });

  it("bez opisu zwraca null także dla Traffita", () => {
    expect(
      agreementProjectDescription({ external_source: "traffit", description: "  " }),
    ).toBeNull();
    expect(agreementProjectDescription(null)).toBeNull();
  });
});
