import { describe, expect, it } from "vitest";

import { EMPTY_PROFILE_FORM } from "@/components/hr/people/ProfileFieldsForm";
import type { PersonLifecycleSummary } from "@/lib/api/hr-lifecycle";

import { lifecycleSummaryLine } from "../LifecycleProfileSection";
import {
  canDeactivateNow,
  formatMoment,
  formatOffset,
  progressLabel,
  workingDays,
} from "../lifecycle-format";
import { onboardingProfile, stepProblem } from "../OnboardingWizard";

describe("dni robocze po polsku", () => {
  it.each([
    [1, "1 dzień roboczy"],
    [2, "2 dni robocze"],
    [4, "4 dni robocze"],
    [5, "5 dni roboczych"],
    [12, "12 dni roboczych"],
    [22, "22 dni robocze"],
    [-2, "2 dni robocze"],
  ])("%i → %s", (count, label) => {
    expect(workingDays(count)).toBe(label);
  });

  it("opisuje termin względem startu i ostatniego dnia", () => {
    expect(formatOffset("onboarding", -2)).toBe("2 dni robocze przed startem");
    expect(formatOffset("onboarding", 0)).toBe("w dniu startu");
    expect(formatOffset("offboarding", 1)).toBe("1 dzień roboczy po ostatnim dniu");
    expect(formatOffset("offboarding", 0)).toBe("w ostatnim dniu");
  });
});

describe("daty", () => {

  it("chwila przekazania w czasie Warszawy", () => {
    // 17:00 UTC w listopadzie = 18:00 w Warszawie.
    expect(formatMoment("2026-11-30T17:00:00Z")).toContain("18:00");
  });
});

describe("postęp i wyłączenie konta", () => {
  it("liczy zadania i zaległe", () => {
    expect(progressLabel({ done: 2, total: 6, overdue: 0 })).toBe("2 z 6 zadań");
    expect(progressLabel({ done: 0, total: 1, overdue: 1 })).toBe(
      "0 z 1 zadania · 1 po terminie",
    );
    expect(progressLabel({ done: 0, total: 0, overdue: 0 })).toBe("bez zadań");
  });

  it("„Wyłącz konto teraz” dopiero w dniu wyłączenia i tylko raz", () => {
    expect(canDeactivateNow("2026-12-01", null, "active", "2026-11-30")).toBe(false);
    expect(canDeactivateNow("2026-12-01", null, "active", "2026-12-01")).toBe(true);
    expect(canDeactivateNow("2026-12-01", "2026-12-01T00:05:00Z", "active", "2026-12-02")).toBe(
      false,
    );
    expect(canDeactivateNow("2026-12-01", null, "cancelled", "2026-12-02")).toBe(false);
  });
});

describe("kreator wejścia", () => {
  const base = { mode: "account" as const, userId: "", email: "", name: "", start: "" };

  it("wymaga konta albo imienia i poprawnego e-maila", () => {
    expect(stepProblem(0, base)).toBe("Wybierz konto.");
    expect(stepProblem(0, { ...base, userId: "7" })).toBeNull();
    expect(stepProblem(0, { ...base, mode: "new", name: "Kacper Przykładowy" })).toBe(
      "Podaj poprawny adres e-mail.",
    );
    expect(
      stepProblem(0, {
        ...base,
        mode: "new",
        name: "Kacper Przykładowy",
        email: "kacper@example.com",
      }),
    ).toBeNull();
    expect(stepProblem(1, base)).toBe("Podaj datę startu.");
    expect(stepProblem(1, { ...base, start: "2026-11-02" })).toBeNull();
  });

  it("nie wysyła statusu ani ostatniego dnia z formularza kartoteki", () => {
    const payload = onboardingProfile({
      ...EMPTY_PROFILE_FORM,
      employment_status: "exited",
      last_working_day: "2026-12-31",
      job_title: "  Rekruter ",
      department: "",
    });
    expect(payload).not.toHaveProperty("employment_status");
    expect(payload).not.toHaveProperty("last_working_day");
    expect(payload.job_title).toBe("Rekruter");
    expect(payload.department).toBeNull();
  });
});

describe("sekcja w kartotece", () => {
  const summary = (overrides: Partial<NonNullable<PersonLifecycleSummary["case"]>>) =>
    ({
      can_manage: true,
      case: {
        id: 1,
        kind: "offboarding",
        status: "active",
        start_date: null,
        last_working_day: "2026-11-30",
        deactivate_on: "2026-12-01",
        handover_executed_at: null,
        account_closed_at: null,
        account_close_result: null,
        progress: { done: 2, total: 6, overdue: 0 },
        link: "/people/5/offboarding",
        ...overrides,
      },
    }) satisfies PersonLifecycleSummary;

  it("mówi, co się dzieje ze sprawą", () => {
    expect(lifecycleSummaryLine(summary({}))).toBe(
      "Odejście · ostatni dzień pon 30.11 · 2 z 6 zadań",
    );
    expect(lifecycleSummaryLine(summary({ account_close_result: "deactivated" }))).toBe(
      "Odejście · ostatni dzień pon 30.11 · Konto wyłączone",
    );
    expect(
      lifecycleSummaryLine(
        summary({ kind: "onboarding", start_date: "2026-11-02", last_working_day: null }),
      ),
    ).toBe("Wejście · start pon 02.11 · 2 z 6 zadań");
    expect(lifecycleSummaryLine({ case: null, can_manage: false })).toBeNull();
  });
});
