/**
 * „Szczegóły administracyjne” umowy (0524): podpowiedzi, kompletność,
 * ładunek, odtworzenie przy „Popraw umowę”, gwarancja i termin premii przy FTE.
 */
import { describe, expect, it } from "vitest";

import type { B2BReplaceableContract } from "@/lib/api";
import {
  adminDefaults,
  adminFromSaved,
  adminPayload,
  bonusBusinessDays,
  EMPTY_ADMIN_VALUE,
  isAdminComplete,
  monthsWorked,
  underWarranty,
} from "@/lib/agreement-admin-details";

// Osoba zastąpiona po 5 miesiącach (01.04–31.08.2026) — gwarancja.
const REPLACED: B2BReplaceableContract = {
  contract_id: 497,
  candidate_id: 3003,
  client_id: 39,
  name: "Zofia Przykładowa",
  client_name: "Klient Testowy S.A.",
  job_title: null,
  status: "ended",
  start_date: "2026-04-01",
  end_date: "2026-08-31",
};

describe("adminDefaults", () => {
  it("zwykła rekrutacja: Nie i pełny etat", () => {
    expect(
      adminDefaults({
        client_id: 39,
        client_name: "Klient Testowy",
        recruiter: null,
        delivery_lead: null,
        replacement_from_title: false,
        replaced: null,
      }),
    ).toEqual({ isReplacement: false, replaced: null, fte: "1" });
  });

  it("zastępstwo z tytułu bierze wskazaną osobę", () => {
    const value = adminDefaults({
      client_id: 39,
      client_name: "Klient Testowy",
      recruiter: null,
      delivery_lead: null,
      replacement_from_title: true,
      replaced: REPLACED,
    });
    expect(value).toEqual({
      isReplacement: true,
      replaced: REPLACED,
      fte: "1",
    });
    expect(isAdminComplete(value)).toBe(true);
  });

  it("zastępstwo bez jednoznacznej osoby czeka na wybór", () => {
    const value = adminDefaults({
      client_id: 11,
      client_name: "Inny Klient",
      recruiter: null,
      delivery_lead: null,
      replacement_from_title: true,
      replaced: null,
    });
    expect(value.isReplacement).toBe(true);
    expect(isAdminComplete(value)).toBe(false);
  });
});

describe("isAdminComplete i adminPayload", () => {
  it("pusty kafelek nie jest kompletny", () => {
    expect(isAdminComplete(EMPTY_ADMIN_VALUE)).toBe(false);
  });

  it("Nie nie wysyła osoby, nawet gdy została w stanie", () => {
    expect(
      adminPayload({ isReplacement: false, replaced: REPLACED, fte: "0.5" }),
    ).toEqual({
      is_replacement: false,
      replaced_contract_id: null,
      fte: "0.5",
    });
  });

  it("Tak wysyła kontrakt osoby zastąpionej", () => {
    expect(
      adminPayload({ isReplacement: true, replaced: REPLACED, fte: "1" }),
    ).toEqual({ is_replacement: true, replaced_contract_id: 497, fte: "1" });
  });
});

describe("adminFromSaved", () => {
  it("umowa sprzed kafelka nie ma czego odtworzyć", () => {
    expect(adminFromSaved({}, null)).toBeNull();
  });

  it("odtwarza zapisany wybór, FTE z liczby z serwera", () => {
    expect(
      adminFromSaved(
        {
          is_replacement: true,
          replaced_contract_id: 497,
          fte: "0.50" as never,
        },
        REPLACED,
      ),
    ).toEqual({ isReplacement: true, replaced: REPLACED, fte: "0.5" });
  });
});

describe("gwarancja i termin premii", () => {
  it("5 miesięcy pracy osoby zastąpionej — gwarancja", () => {
    expect(monthsWorked(REPLACED)).toBe(5);
    expect(underWarranty(REPLACED)).toBe(true);
  });

  it("dokładnie rok to już nie gwarancja", () => {
    const year = {
      ...REPLACED,
      start_date: "2025-10-02",
      end_date: "2026-10-01",
    };
    expect(monthsWorked(year)).toBe(12);
    expect(underWarranty(year)).toBe(false);
  });

  it("bez daty końca nie liczymy", () => {
    expect(monthsWorked({ ...REPLACED, end_date: null })).toBeNull();
    expect(
      underWarranty({ ...REPLACED, status: "active", end_date: null }),
    ).toBe(false);
  });

  it("168 h przy FTE", () => {
    expect(bonusBusinessDays("1")).toBe(21);
    expect(bonusBusinessDays("0.75")).toBe(28);
    expect(bonusBusinessDays("0.5")).toBe(42);
    expect(bonusBusinessDays("0.25")).toBe(84);
  });
});
