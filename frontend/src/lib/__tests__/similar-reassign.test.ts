import { describe, expect, it } from "vitest";

import type { SentPerson } from "@/lib/similar-jobs-api";
import {
  personStatusLine,
  planReassign,
  pluralPeople,
  similarPeopleWaiting,
} from "@/lib/similar-reassign";

function person(overrides: Partial<SentPerson> & { candidate_id: number }): SentPerson {
  return {
    name: `Osoba ${overrides.candidate_id}`,
    furthest_stage: "cv_sent",
    sent_at: "2026-09-12",
    outcome: "in_progress",
    already_in_job: false,
    selectable: true,
    ...overrides,
  };
}

describe("planReassign — kliknięta rekrutacja zaznacza swoich wysłanych", () => {
  it("zaznacza wszystkich wysłanych, także odrzuconych przez klienta", () => {
    const plan = planReassign(
      [1],
      {
        1: [
          person({ candidate_id: 10 }),
          person({ candidate_id: 11, outcome: "rejected_by_client" }),
        ],
      },
      new Set(),
    );
    expect(plan.candidateIds).toEqual([10, 11]);
    expect(plan.rows[1].map((r) => r.state)).toEqual(["selected", "selected"]);
  });

  it("zatrudnionych i obecnych w tej rekrutacji nie da się przepiąć", () => {
    const plan = planReassign(
      [1],
      {
        1: [
          person({ candidate_id: 10 }),
          person({ candidate_id: 12, outcome: "hired", selectable: false }),
          person({ candidate_id: 13, already_in_job: true, selectable: false }),
        ],
      },
      new Set(),
    );
    expect(plan.candidateIds).toEqual([10]);
    expect(plan.rows[1].map((r) => r.state)).toEqual(["selected", "locked", "locked"]);
  });

  it("osoba z dwóch rekrutacji liczy się raz — przy pierwszej klikniętej", () => {
    const plan = planReassign(
      [2, 1],
      {
        1: [person({ candidate_id: 10 }), person({ candidate_id: 11 })],
        2: [person({ candidate_id: 11 })],
      },
      new Set(),
    );
    expect(plan.candidateIds).toEqual([11, 10]);
    expect(plan.rows[2][0].state).toBe("selected");
    expect(plan.rows[1].map((r) => r.state)).toEqual(["selected", "duplicate"]);
  });

  it("odznaczona osoba nie jest przepinana", () => {
    const plan = planReassign(
      [1],
      { 1: [person({ candidate_id: 10 }), person({ candidate_id: 11 })] },
      new Set([11]),
    );
    expect(plan.candidateIds).toEqual([10]);
    expect(plan.rows[1][1].state).toBe("unselected");
  });

  it("rekrutacja, której ludzie jeszcze się wczytują, nic nie przepina", () => {
    const plan = planReassign([1], { 1: undefined }, new Set());
    expect(plan.candidateIds).toEqual([]);
    expect(plan.rows[1]).toBeUndefined();
  });
});

describe("similarPeopleWaiting", () => {
  it("bierze liczbę osób do przepięcia policzoną przez serwer, nie sumę wysłanych", () => {
    expect(similarPeopleWaiting({ reassignable_people: 3 })).toBe(3);
    expect(similarPeopleWaiting({ reassignable_people: 0 })).toBe(0);
    // Brak liczby = nie wiadomo; nagłówek i „Najbliższy krok” milczą.
    expect(similarPeopleWaiting({})).toBeNull();
    expect(similarPeopleWaiting(undefined)).toBeNull();
  });
});

describe("opis osoby", () => {
  it("mówi, jak skończył się tamten proces", () => {
    expect(personStatusLine(person({ candidate_id: 1 }))).toBe(
      "CV wysłane 12.09.2026 · proces trwa",
    );
    expect(
      personStatusLine(
        person({
          candidate_id: 2,
          furthest_stage: "client_interview",
          outcome: "rejected_by_client",
        }),
      ),
    ).toBe("rozmowa u klienta · klient odrzucił");
  });

  it("odmienia liczbę osób", () => {
    expect([1, 2, 5, 12, 22].map(pluralPeople)).toEqual([
      "osobę",
      "osoby",
      "osób",
      "osób",
      "osoby",
    ]);
  });
});
