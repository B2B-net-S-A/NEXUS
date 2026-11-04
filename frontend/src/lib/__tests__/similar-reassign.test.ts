import { describe, expect, it } from "vitest";

import type { SentPerson } from "@/lib/similar-jobs-api";
import {
  personStatusLine,
  planReassign,
  previewSequence,
  pluralPeople,
  similarPeopleTotal,
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

describe("previewSequence — kolejność podglądu osób", () => {
  it("idzie grupami w kolejności ekranu, osoba z dwóch rekrutacji wchodzi raz", () => {
    const plan = planReassign(
      [2, 1],
      {
        1: [person({ candidate_id: 10 }), person({ candidate_id: 11 })],
        2: [person({ candidate_id: 11 }), person({ candidate_id: 12, selectable: false })],
      },
      new Set([10]),
    );
    // Kliknięto najpierw 2, ale na ekranie pierwsza stoi rekrutacja 1.
    const sequence = previewSequence([1, 2], plan.rows);
    expect(sequence.map((e) => [e.jobId, e.person.candidate_id])).toEqual([
      [1, 10],
      [1, 11],
      [2, 12],
    ]);
  });

  it("rekrutacja bez wczytanych osób i pusta nic nie dokładają", () => {
    const plan = planReassign([1, 2, 3], { 1: [], 3: [person({ candidate_id: 7 })] }, new Set());
    expect(previewSequence([1, 2, 3], plan.rows).map((e) => e.person.candidate_id)).toEqual([7]);
    expect(previewSequence([], plan.rows)).toEqual([]);
  });
});

describe("planReassign — „pozostali” z rekrutacji (klient ich nie widział)", () => {
  const people = {
    1: [
      person({ candidate_id: 10 }),
      person({ candidate_id: 20, sent: false, sent_at: null, furthest_stage: "screening" }),
      person({ candidate_id: 21, sent: false, sent_at: null, furthest_stage: "verified" }),
    ],
  };

  it("nie zaznaczają się sami — wybiera ich człowiek", () => {
    const plan = planReassign([1], people, new Set());
    expect(plan.candidateIds).toEqual([10]);
    expect(plan.restIds).toEqual([]);
    expect(plan.rows[1].map((r) => r.state)).toEqual(["selected", "unselected", "unselected"]);
  });

  it("zaznaczony „pozostały” idzie osobną listą, nie przepięciem", () => {
    const plan = planReassign([1], people, new Set(), new Set([21]));
    expect(plan.candidateIds).toEqual([10]);
    expect(plan.restIds).toEqual([21]);
    expect(plan.rows[1].map((r) => r.state)).toEqual(["selected", "unselected", "selected"]);
  });

  it("osoba wysłana do klienta w innej wybranej rekrutacji jest przepięciem, nie „pozostałą”", () => {
    const plan = planReassign(
      [1, 2],
      {
        1: [person({ candidate_id: 30, sent: false, sent_at: null, furthest_stage: "screening" })],
        2: [person({ candidate_id: 30 })],
      },
      new Set(),
      new Set([30]),
    );
    expect(plan.candidateIds).toEqual([30]);
    expect(plan.restIds).toEqual([]);
    expect(plan.rows[1][0].state).toBe("duplicate");
    expect(plan.rows[2][0].state).toBe("selected");
  });

  it("opis mówi, dokąd osoba doszła", () => {
    expect(
      personStatusLine(
        person({ candidate_id: 20, sent: false, sent_at: null, furthest_stage: "screening", outcome: "rejected" }),
      ),
    ).toBe("najdalej: screening · odrzucony");
  });
});

describe("similarPeopleTotal — liczba na kaflu „Podobne rekrutacje”", () => {
  it("sumuje wysłanych i pozostałych", () => {
    expect(similarPeopleTotal({ reassignable_people: 19, other_people: 6 })).toEqual({
      sent: 19,
      other: 6,
      total: 25,
    });
  });

  it("starszy serwer bez „pozostałych” = sami wysłani; brak danych = null", () => {
    expect(similarPeopleTotal({ reassignable_people: 3 })).toEqual({ sent: 3, other: 0, total: 3 });
    expect(similarPeopleTotal(undefined)).toBeNull();
  });
});
