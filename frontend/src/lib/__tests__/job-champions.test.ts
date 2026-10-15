/**
 * Championi rekrutacji (D1–D9, 15.10.2026): napis plakietki statusu, grupy
 * w okienku, zdania o skutkach zapisu i odrzucenia championa.
 */
import { describe, expect, it } from "vitest";

import {
  CHAMPION_EFFECT_RESUME,
  CHAMPION_EFFECT_STOP,
  championWorkStateLine,
  championEffectLines,
  championRemovalOutcome,
  championSeats,
  championStatusView,
  championsTitle,
  filterChampionCandidates,
  groupChampionCandidates,
  type ChampionCandidate,
} from "@/lib/job-champions";

const KAROL = { candidate_id: 1, name: "Karol Wzorcowy" };
const BARTEK = { candidate_id: 2, name: "Bartek Testowy" };
const IZA = { candidate_id: 3, name: "Iza Umowna" };

describe("plakietka statusu w nagłówku", () => {
  it("stara flaga bez osób: „Mamy championa” w złotym tonie (D1)", () => {
    const view = championStatusView({ request_status: "champion", champions: [] });
    expect(view).toMatchObject({ kind: "legacy", label: "Mamy championa", tone: "champion" });
  });

  it("jeden champion: imię i inicjał nazwiska, pełne imię w dymku", () => {
    const view = championStatusView({ request_status: "champion", champions: [KAROL] });
    expect(view).toMatchObject({ kind: "named", label: "Champion: Karol W.", tone: "champion" });
    expect(view?.title).toContain("Champion: Karol Wzorcowy");
  });

  it("dwóch championów: pierwszy skrótem i „+1”, obaj w dymku", () => {
    const view = championStatusView({ request_status: "champion", champions: [KAROL, BARTEK] });
    expect(view?.label).toBe("Championi: Karol W. +1");
    expect(view?.title).toContain("Championi: Karol Wzorcowy, Bartek Testowy");
  });

  it("mniej championów niż miejsc: „Szukamy · 1 z 2” w tonie szukania (D5)", () => {
    const view = championStatusView({
      request_status: "searching",
      champions: [KAROL],
      champion_seats: 2,
    });
    expect(view).toMatchObject({
      kind: "partial",
      label: "Szukamy · 1 z 2",
      lead: "Szukamy",
      seatsText: "1 z 2",
      tone: "search",
    });
  });

  it("bez championów: etykieta statusu jak na liście; nieznany status = null", () => {
    expect(championStatusView({ request_status: "searching", champions: [] })).toMatchObject({
      kind: "plain",
      label: "Szukamy",
      tone: "search",
    });
    expect(championStatusView({ request_status: "contract" })?.label).toBe("Umowa");
    expect(championStatusView({ request_status: "cokolwiek" })).toBeNull();
    expect(championStatusView({})).toBeNull();
  });

  it("miejsca jak na serwerze: max(headcount, 1)", () => {
    expect(championSeats({ champion_seats: 3 })).toBe(3);
    expect(championSeats({ champion_seats: 0 })).toBe(1);
    expect(championSeats({ champion_seats: null })).toBe(1);
  });

  it("dymek listy: liczba pojedyncza i mnoga", () => {
    expect(championsTitle([KAROL])).toBe("Champion: Karol Wzorcowy");
    expect(championsTitle([KAROL, BARTEK])).toBe("Championi: Karol Wzorcowy, Bartek Testowy");
    expect(championsTitle([])).toBe("");
  });
});

describe("okienko: grupy i wyszukiwanie", () => {
  const person = (
    candidate_id: number,
    name: string,
    column: string | null,
  ): ChampionCandidate => ({ candidate_id, name, column, stage_label: null });

  it("grupy od najdalszej kolumny, w grupie kolejność serwera, nieznana kolumna na końcu", () => {
    const groups = groupChampionCandidates([
      person(1, "Anna Przykładowa", "cv_sent"),
      person(2, "Bartek Testowy", "client_interview"),
      person(3, "Celina Próbna", null),
      person(4, "Iza Umowna", "contract"),
      person(5, "Karol Wzorcowy", "client_interview"),
      person(6, "Zofia Szkicowa", "hired"),
    ]);
    expect(groups.map((g) => g.label)).toEqual([
      "Zatrudniony",
      "Umowa",
      "Rozmowa u klienta",
      "CV wysłane",
      "Inny etap",
    ]);
    expect(groups[2].items.map((p) => p.name)).toEqual(["Bartek Testowy", "Karol Wzorcowy"]);
  });

  it("rekrutacja z kolejką Cpro: „CV wysłane” nazywa się jak kolumna Tablicy", () => {
    const groups = groupChampionCandidates([person(1, "Anna Przykładowa", "cv_sent")], {
      cproEnabled: true,
    });
    expect(groups[0].label).toBe("Wysłane do Cpro");
  });

  it("szukanie bez wielkości liter i polskich znaków", () => {
    const people = [person(1, "Łucja Próbna", "cv_sent"), person(2, "Karol Wzorcowy", "cv_sent")];
    expect(filterChampionCandidates(people, "lucja prob").map((p) => p.candidate_id)).toEqual([1]);
    expect(filterChampionCandidates(people, "  ")).toHaveLength(2);
    expect(filterChampionCandidates(people, "nikt")).toEqual([]);
  });
});

describe("okienko: zdania o skutkach zapisu", () => {
  const base = { seats: 1, hiredCount: 0, hadChampions: false, workState: "searching" };

  it("zaznaczeni pokrywają miejsca → rekrutacja nie szuka", () => {
    expect(
      championEffectLines({ ...base, selected: [{ column: "client_interview" }] }),
    ).toEqual([CHAMPION_EFFECT_STOP]);
  });

  it("za mało na miejsca → szukamy dalej z liczbą", () => {
    expect(
      championEffectLines({ ...base, seats: 2, selected: [{ column: "client_interview" }] }),
    ).toEqual(["Szukamy dalej: 1 z 2 miejsc ma championa."]);
  });

  it("zatrudniony liczy się raz: champion w „Zatrudniony” nie dubluje miejsca", () => {
    expect(
      championEffectLines({ ...base, seats: 2, hiredCount: 1, selected: [{ column: "hired" }] }),
    ).toEqual(["Szukamy dalej: 1 z 2 miejsc ma championa."]);
    expect(
      championEffectLines({ ...base, seats: 2, hiredCount: 1, selected: [{ column: "contract" }] }),
    ).toEqual([CHAMPION_EFFECT_STOP]);
  });

  it("nikt zaznaczony, a wcześniej byli championi albo flaga → wraca „Szukamy”", () => {
    expect(championEffectLines({ ...base, hadChampions: true, selected: [] })).toEqual([
      CHAMPION_EFFECT_RESUME,
    ]);
    expect(championEffectLines({ ...base, selected: [] })).toEqual([]);
  });

  it("„Do przejrzenia” albo „Klient milczy” z championem → request wraca do „Szukamy” (D9)", () => {
    for (const workState of ["to_review", "client_silent"] as const) {
      expect(
        championEffectLines({ ...base, workState, selected: [{ column: "cv_sent" }] }),
      ).toEqual([CHAMPION_EFFECT_STOP, championWorkStateLine(workState)]);
    }
    expect(championWorkStateLine("client_silent")).toContain("„Klient milczy”");
    expect(championEffectLines({ ...base, workState: "to_review", selected: [] })).toEqual([]);
  });
});

describe("odrzucenie championa (D7)", () => {
  it("osoba spoza listy championów → bez zdania", () => {
    expect(
      championRemovalOutcome(
        { champions: [KAROL], champion_seats: 1, hired_count: 0 },
        BARTEK.candidate_id,
        "Bartek Testowy",
      ),
    ).toBeNull();
  });

  it("zatrudniony champion liczy się raz — jak na serwerze (suma zbiorów)", () => {
    // Dwa miejsca: Karol zatrudniony i championem, Bartek championem. Bez
    // Bartka zostaje {Karol} ∪ {Karol} = 1 < 2 — szukanie wraca.
    expect(
      championRemovalOutcome(
        {
          champions: [{ ...KAROL, hired: true }, BARTEK],
          champion_seats: 2,
          hired_count: 1,
        },
        BARTEK.candidate_id,
        "Bartek Testowy",
      ),
    ).toBe(
      "Bartek jest championem. Po odrzuceniu zostanie 1 z 2 championów — rekrutacja wróci do „Szukamy”.",
    );
  });

  it("zostaje inny champion na wszystkie miejsca → dalej nie szukamy", () => {
    expect(
      championRemovalOutcome(
        { champions: [KAROL, BARTEK], champion_seats: 1, hired_count: 0 },
        KAROL.candidate_id,
        "Karol Wzorcowy",
      ),
    ).toBe("Karol jest championem. Zostaje Bartek T., więc rekrutacja dalej nie szuka.");
  });

  it("ostatni champion → wraca „Szukamy”, a wstrzymany P1 zaczyna działać", () => {
    expect(
      championRemovalOutcome(
        { champions: [KAROL], champion_seats: 1, hired_count: 0, priority_paused: true },
        KAROL.candidate_id,
        "Karol Wzorcowy",
      ),
    ).toBe(
      "Karol jest ostatnim championem. Po odrzuceniu rekrutacja wróci do „Szukamy”, a P1 zacznie działać.",
    );
    // Bez P1 nie ma czego wznawiać.
    expect(
      championRemovalOutcome(
        { champions: [KAROL], champion_seats: 1, hired_count: 0, priority_paused: false },
        KAROL.candidate_id,
        "Karol Wzorcowy",
      ),
    ).toBe("Karol jest ostatnim championem. Po odrzuceniu rekrutacja wróci do „Szukamy”.");
  });

  it("zostają inni, ale za mało na miejsca → liczba i powrót do „Szukamy”", () => {
    expect(
      championRemovalOutcome(
        { champions: [KAROL, BARTEK, IZA], champion_seats: 3, hired_count: 0 },
        IZA.candidate_id,
        "Iza Umowna",
      ),
    ).toBe(
      "Iza jest championem. Po odrzuceniu zostanie 2 z 3 championów — rekrutacja wróci do „Szukamy”.",
    );
  });

  it("rekrutacja i tak szukała (miejsc więcej niż championów) → bez zapowiedzi powrotu", () => {
    expect(
      championRemovalOutcome(
        { champions: [KAROL, BARTEK], champion_seats: 3, hired_count: 0 },
        KAROL.candidate_id,
        "Karol Wzorcowy",
      ),
    ).toBe("Karol jest championem. Po odrzuceniu zostanie 1 z 3 championów.");
    expect(
      championRemovalOutcome(
        { champions: [KAROL], champion_seats: 2, hired_count: 0 },
        KAROL.candidate_id,
        "Karol Wzorcowy",
      ),
    ).toBe("Karol jest ostatnim championem tej rekrutacji.");
  });

  it("zatrudnieni dopełniają miejsca → nadal nie szukamy", () => {
    expect(
      championRemovalOutcome(
        { champions: [KAROL, BARTEK], champion_seats: 2, hired_count: 1 },
        KAROL.candidate_id,
        "Karol Wzorcowy",
      ),
    ).toBe("Karol jest championem. Zostaje Bartek T., więc rekrutacja dalej nie szuka.");
  });

  it("bez detalu rekrutacji w cache'u okno nic nie zgaduje", () => {
    expect(championRemovalOutcome(undefined, 1, "Karol Wzorcowy")).toBeNull();
    expect(championRemovalOutcome({ request_status: "champion" }, 1, "Karol Wzorcowy")).toBeNull();
  });
});
