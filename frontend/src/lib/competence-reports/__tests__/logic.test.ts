import { describe, expect, it } from "vitest";

import { apiErrorMessage } from "@/lib/api-error";

import {
  canEdit,
  canHold,
  canRelease,
  canSendNow,
  conditionsFromDraft,
  draftFromConditions,
  formatDeadline,
  statusChips,
  type ConditionsDraft,
} from "../logic";

const NOW = new Date("2026-11-25T12:00:00Z");

function due(minutesFromNow: number): string {
  return new Date(NOW.getTime() + minutesFromNow * 60_000).toISOString();
}

describe("formatDeadline — licznik do wysyłki", () => {
  it("godziny i minuty przed terminem", () => {
    expect(formatDeadline({ status: "ready", held: false, send_due_at: due(320) }, NOW)).toEqual({
      text: "za 5 h 20 min",
      tone: "ok",
    });
    expect(formatDeadline({ status: "ready", held: false, send_due_at: due(240) }, NOW).text).toBe(
      "za 4 h",
    );
  });

  it("poniżej 3 godzin i przy wstrzymaniu świeci ostrzegawczo", () => {
    expect(formatDeadline({ status: "ready", held: false, send_due_at: due(40) }, NOW)).toEqual({
      text: "za 40 min",
      tone: "soon",
    });
    expect(formatDeadline({ status: "ready", held: true, send_due_at: due(600) }, NOW).tone).toBe(
      "soon",
    );
  });

  it("po terminie liczy, ile minęło", () => {
    expect(formatDeadline({ status: "waiting_cv", held: true, send_due_at: due(-65) }, NOW)).toEqual({
      text: "po terminie 1 h 5 min",
      tone: "late",
    });
    expect(formatDeadline({ status: "ready", held: false, send_due_at: due(0) }, NOW).tone).toBe("late");
  });

  it("raport rozstrzygnięty i zła data nie mają licznika", () => {
    expect(formatDeadline({ status: "sent", held: false, send_due_at: due(60) }, NOW)).toEqual({
      text: "—",
      tone: "done",
    });
    expect(formatDeadline({ status: "ready", held: false, send_due_at: "zła" }, NOW).tone).toBe("done");
  });
});

describe("statusChips i dozwolone akcje", () => {
  it("stan słowami, „Wstrzymany” osobno i tylko w kolejce", () => {
    expect(statusChips({ status: "ready", held: false })).toEqual([{ label: "Gotowy", tone: "info" }]);
    expect(statusChips({ status: "waiting_cv", held: true }).map((c) => c.label)).toEqual([
      "Czeka na CV",
      "Wstrzymany",
    ]);
    expect(statusChips({ status: "sent", held: true }).map((c) => c.label)).toEqual(["Wysłany"]);
    expect(statusChips({ status: "failed", held: false })[0].tone).toBe("danger");
  });

  it("„Wyślij teraz” tylko z gotowym snapshotem, nic po wysyłce", () => {
    expect(canSendNow({ status: "ready", snapshot: {} })).toBe(true);
    expect(canSendNow({ status: "failed", snapshot: {} })).toBe(true);
    expect(canSendNow({ status: "waiting_cv", snapshot: null })).toBe(false);
    expect(canSendNow({ status: "sent", snapshot: {} })).toBe(false);
    expect(canHold({ status: "ready", held: false })).toBe(true);
    expect(canHold({ status: "ready", held: true })).toBe(false);
    expect(canRelease({ status: "ready", held: true })).toBe(true);
    expect(canEdit({ status: "opted_out" })).toBe(false);
  });
});

describe("conditionsFromDraft — te same granice co backend", () => {
  const base: ConditionsDraft = draftFromConditions({
    rate: 150,
    contract: "b2b",
    modes: ["hybrid"],
    office_days_max: 2,
    office_cities: ["Kraków"],
    start: "1m",
  });

  it("odtwarza warunki z formularza", () => {
    expect(conditionsFromDraft({ ...base, office_cities: " Kraków, Gdańsk ,Kraków, " })).toEqual({
      ok: true,
      body: {
        rate: 150,
        current_rate: null,
        contract: "b2b",
        modes: ["hybrid"],
        office_days_max: 2,
        office_cities: ["Kraków", "Gdańsk"],
        start: "1m",
      },
    });
  });

  it("odmawia stawki spoza 1–2000, dni spoza 0–5 i pustej stawki", () => {
    const bad = (patch: Partial<ConditionsDraft>) => {
      const result = conditionsFromDraft({ ...base, ...patch });
      return result.ok ? [] : Object.keys(result.errors);
    };
    expect(bad({ rate: "" })).toEqual(["rate"]);
    expect(bad({ rate: "0" })).toEqual(["rate"]);
    expect(bad({ rate: "2001" })).toEqual(["rate"]);
    expect(bad({ rate: "150.5" })).toEqual(["rate"]);
    expect(bad({ current_rate: "-3" })).toEqual(["current_rate"]);
    expect(bad({ office_days_max: "6" })).toEqual(["office_days_max"]);
    expect(bad({ office_days_max: "" })).toEqual([]);
  });

  it("tryby w stałej kolejności, pusty start = brak", () => {
    const result = conditionsFromDraft({ ...base, modes: ["onsite", "remote"], start: "" });
    expect(result.ok && result.body.modes).toEqual(["remote", "onsite"]);
    expect(result.ok && result.body.start).toBeNull();
  });
});

describe("„Wyślij teraz” — powód z 409", () => {
  it("pokazuje zdanie z backendu zamiast ogólnego błędu", () => {
    const error = {
      response: {
        status: 409,
        data: {
          detail: "Mail „Raport kompetencji” jest wyłączony w Ustawieniach powiadomień.",
          reason: "mail_disabled",
        },
      },
    };
    expect(apiErrorMessage(error, "Nie udało się wysłać raportu.")).toBe(
      "Mail „Raport kompetencji” jest wyłączony w Ustawieniach powiadomień.",
    );
  });
});
