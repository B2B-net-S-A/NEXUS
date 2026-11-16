/**
 * Strażnik widełek w ogłoszeniu (16.11.2026): tekst UoP mówi o wymogu prawa,
 * B2B — „zalecane” bez przesądzania; bez widełek wysyłka dopiero z powodem.
 */

import { describe, expect, it, vi } from "vitest";

import { EMPTY_LISTING_OPTIONS, type PortalListingOptions } from "@/lib/api/jobPortals";
import {
  confirmSalaryOrReason,
  noSalaryDescription,
  noSalaryReasonRequest,
} from "@/lib/postingSalaryGuard";

const BARE: PortalListingOptions = { ...EMPTY_LISTING_OPTIONS, city: "Warszawa" };
const WITH_SALARY: PortalListingOptions = {
  ...BARE,
  salary: { from: 150, to: 190, unit: "hour" },
  no_salary_reason: "stary powód",
};

describe("teksty", () => {
  it("umowa o pracę: wymaga tego prawo", () => {
    const text = noSalaryDescription("uop");
    expect(text).toContain("prawo wymaga");
    expect(text).toContain("Dz.U. 2025 poz. 807");
    expect(text).toContain("przed rozmową");
  });

  it("B2B: zalecane, zakres prawa sprawdzany", () => {
    const text = noSalaryDescription("b2b");
    expect(text).toContain("zalecane");
    expect(text).toContain("sprawdzamy z prawnikiem");
    expect(text).not.toContain("wymaga");
  });

  it("pole powodu ma minimum i limit, edycja mówi „Zapisz”", () => {
    const request = noSalaryReasonRequest("b2b", { editing: true });
    expect(request.field.minLength).toBe(3);
    expect(request.field.maxLength).toBe(300);
    expect(request.confirmLabel).toBe("Zapisz bez widełek");
    expect(noSalaryReasonRequest("b2b").confirmLabel).toBe("Opublikuj bez widełek");
  });
});

describe("confirmSalaryOrReason", () => {
  it("z widełkami nie pyta i czyści stary powód", async () => {
    const askReason = vi.fn();
    expect(await confirmSalaryOrReason(WITH_SALARY, askReason)).toEqual({
      ...WITH_SALARY,
      no_salary_reason: null,
    });
    expect(askReason).not.toHaveBeenCalled();
  });

  it("bez widełek dokłada powód z potwierdzenia", async () => {
    const askReason = vi.fn(async () => "Stawka po rozmowie.");
    expect(await confirmSalaryOrReason(BARE, askReason, { form: "uop" })).toEqual({
      ...BARE,
      no_salary_reason: "Stawka po rozmowie.",
    });
    expect(askReason).toHaveBeenCalledWith(
      expect.objectContaining({ description: noSalaryDescription("uop") }),
    );
  });

  it("anulowanie albo za krótki powód = nic nie wychodzi", async () => {
    expect(await confirmSalaryOrReason(BARE, vi.fn(async () => null))).toBeNull();
    expect(await confirmSalaryOrReason(BARE, vi.fn(async () => "ok"))).toBeNull();
  });
});
