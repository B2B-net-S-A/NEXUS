import { describe, expect, it } from "vitest";

import { EMPTY_PROFILE_FORM } from "@/components/hr/people/ProfileFieldsForm";
import type { PersonLifecycleSummary } from "@/lib/api/hr-lifecycle";

import { lifecycleSummaryLine } from "../LifecycleProfileSection";
import {
  canDeactivateNow,
  daysFromToday,
  formatMoment,
  formatOffset,
  groupTasksByOwner,
  matchAccounts,
  offboardingMilestones,
  previewByOwner,
  progressLabel,
  workLayout,
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

// ── Makiety 19.10.2026 ────────────────────────────────────────────────────

function task(overrides: Record<string, unknown>) {
  return {
    category: "other",
    status: "open",
    due_date: "2026-11-30",
    done_at: null,
    done_by_name: null,
    assignee_kind: "people_admin",
    assignee_name: null,
    ...overrides,
  };
}

const offboarding = {
  status: "active",
  started_at: "2026-10-19T09:00:00Z",
  last_working_day: "2026-11-30",
  handover_at: "2026-11-30T17:00:00Z",
  handover_executed_at: null,
  deactivate_on: "2026-12-01",
  account_closed_at: null,
};

describe("oś odejścia", () => {
  it("zgłoszone → rozmowa → przekazanie → konto → sprzęt, bieżący pierwszy niezrobiony", () => {
    const steps = offboardingMilestones({
      ...offboarding,
      tasks: [
        task({ category: "meeting", status: "done", done_at: "2026-10-19", done_by_name: "Marta Przykładowa" }),
        task({ category: "equipment", due_date: "2026-12-02", assignee_kind: "reception" }),
      ],
    });
    expect(steps.map((s) => [s.key, s.state])).toEqual([
      ["reported", "done"],
      ["exit_talk", "done"],
      ["handover", "current"],
      ["account", "upcoming"],
      ["equipment", "upcoming"],
    ]);
    expect(steps[1]).toMatchObject({ on: "2026-10-19", who: "Marta Przykładowa" });
    expect(steps[2].on).toBe("2026-11-30T17:00:00Z");
    expect(steps[4].on).toBe("2026-12-02");
  });

  it("bez rozmowy i sprzętu tych kroków nie ma; szkic i cofnięta sprawa", () => {
    const draft = offboardingMilestones({ ...offboarding, status: "draft", started_at: null, tasks: [] });
    expect(draft.map((s) => s.key)).toEqual(["reported", "handover", "account"]);
    expect(draft[0]).toMatchObject({ label: "Szkic", state: "current" });
    const cancelled = offboardingMilestones({ ...offboarding, status: "cancelled", tasks: [] });
    expect(cancelled.some((s) => s.state === "current")).toBe(false);
    const finished = offboardingMilestones({
      ...offboarding,
      handover_executed_at: "2026-11-30T17:00:05Z",
      account_closed_at: "2026-12-01T05:00:00Z",
      tasks: [],
    });
    expect(finished.every((s) => s.state === "done")).toBe(true);
    expect(finished[2].on).toBe("2026-12-01T05:00:00Z");
  });

  it("dni do ostatniego dnia", () => {
    expect(daysFromToday("2026-11-30", "2026-10-19")).toBe("za 42 dni");
    expect(daysFromToday("2026-10-20", "2026-10-19")).toBe("jutro");
    expect(daysFromToday("2026-10-19", "2026-10-19")).toBe("dziś");
    expect(daysFromToday("2026-10-16", "2026-10-19")).toBe("3 dni temu");
    expect(daysFromToday(null, "2026-10-19")).toBeNull();
  });
});

describe("zadania wg właściciela", () => {
  it("grupy od najwcześniejszego terminu, osoba z imieniem, zrobione na końcu", () => {
    const groups = groupTasksByOwner(
      [
        task({ assignee_kind: "it", due_date: "2026-11-30" }),
        task({ assignee_kind: "reception", assignee_name: "Zofia Recepcyjna", due_date: "2026-11-28" }),
        task({ assignee_kind: "reception", assignee_name: "Zofia Recepcyjna", due_date: "2026-11-30" }),
        task({ assignee_kind: "people_admin", status: "done" }),
        task({ assignee_kind: "manager", status: "skipped" }),
      ],
      { it: "IT", reception: "Recepcja", people_admin: "Kadry", manager: "Przełożony" },
    );
    expect(groups.map((g) => [g.label, g.tasks.length])).toEqual([
      ["Recepcja · Zofia", 2],
      ["IT", 1],
      ["Zrobione", 2],
    ]);
    expect(groups[0].person).toBe("Zofia Recepcyjna");
  });
});

describe("kreator wejścia", () => {
  it("„Co powstanie”: wykonawcy w kolejności makiety, nieznani na końcu", () => {
    const tasks = [
      { assignee_kind: "it", title: "Skrzynka" },
      { assignee_kind: "people_admin", title: "Umowa" },
      { assignee_kind: "manager", title: "Rozmowa powitalna" },
      { assignee_kind: "people_admin", title: "BHP" },
      { assignee_kind: "nowy", title: "Coś" },
    ];
    expect(previewByOwner(tasks).map((g) => [g.kind, g.tasks.length])).toEqual([
      ["manager", 1],
      ["people_admin", 2],
      ["it", 1],
      ["nowy", 1],
    ]);
  });

  it("konto: najpierw bez kartoteki, szukanie bez ogonków, z kartoteką tylko po wpisaniu", () => {
    const free = [{ user_id: 1, name: "Kacper Nowicjusz", email: "kacper@example.com" }];
    const people = [
      { user_id: 2, name: "Łucja Kacprzak", email: "lucja@example.com" },
      { user_id: 1, name: "Kacper Nowicjusz", email: "kacper@example.com" },
    ];
    expect(matchAccounts(free, people, "")).toEqual([{ ...free[0], has_profile: false }]);
    expect(matchAccounts(free, people, "kacp").map((a) => [a.user_id, a.has_profile])).toEqual([
      [1, false],
      [2, true],
    ]);
    expect(matchAccounts(free, people, "lucja").map((a) => a.user_id)).toEqual([2]);
    expect(matchAccounts(free, people, "nikt")).toEqual([]);
  });
});

describe("komu przekazać", () => {
  const row = (kind: string, count: number | null, transferable = true, status: string | null = null) => ({
    kind,
    count,
    transferable,
    status,
  });

  it("praca idąca z rekrutacjami pod wierszem rekrutacji, zera zwinięte, wynik zostaje", () => {
    const layout = workLayout([
      row("recruitments", 4),
      row("pipeline_cards", 11, false),
      row("client_meetings", 0, false),
      row("my_people", 37),
      row("reports", 0),
      row("dl_clients", 0, true, "done"),
      row("substitutions", 1, false),
    ]);
    expect(layout.rows.map((r) => r.kind)).toEqual([
      "recruitments",
      "my_people",
      "dl_clients",
      "substitutions",
    ]);
    expect(layout.withRecruitments.map((r) => r.kind)).toEqual(["pipeline_cards"]);
    expect(layout.empty.map((r) => r.kind)).toEqual(["client_meetings", "reports"]);
  });

  it("bez rekrutacji karty zostają osobnym wierszem", () => {
    const layout = workLayout([row("recruitments", 0), row("pipeline_cards", 3, false)]);
    expect(layout.rows.map((r) => r.kind)).toEqual(["pipeline_cards"]);
    expect(layout.empty.map((r) => r.kind)).toEqual(["recruitments"]);
  });
});
