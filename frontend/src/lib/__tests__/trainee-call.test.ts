import { describe, expect, it } from "vitest";

import type { TraineeItem, TraineeToday } from "@/lib/api/trainee";
import {
  emptyCallForm,
  handoverNoteFromFacts,
  handoverNoteFromForm,
  isCompleteProfile,
  laterDateError,
  missingLabel,
  nextBusinessDay,
  nextOpenItemId,
  parseRate,
  profileRateLabel,
  recountToday,
  retryLabel,
  splitItems,
  telHref,
  toCallBody,
  toggleInList,
  toggleValue,
  validateCallForm,
  whyThisPerson,
  type TraineeCallForm,
} from "@/lib/trainee-call";

function item(id: number, over: Partial<TraineeItem> = {}): TraineeItem {
  return {
    id,
    candidate_id: 1000 + id,
    position: id,
    name: `Osoba ${id}`,
    role: "Java Developer",
    company: "Firma",
    city: "Kraków",
    phone: "+48 601 234 518",
    in_base_since: 2023,
    last_contact_at: null,
    attempts: 0,
    retry_after: null,
    outcome: null,
    closed_at: null,
    later_date: null,
    reasons: { fits: 3, open_fits: 1, stack: ["Java"], missing: ["rate_missing"] },
    facts: {
      min_rate_hourly: null,
      rate_updated_at: null,
      b2b_willingness: null,
      accepts_below_min_rate: null,
      remote_modes: [],
      max_onsite_days: null,
      accepts_more_office_days: null,
      office_cities: [],
      work_time_preference: null,
      availability_status: "unknown",
      availability_date: null,
    },
    ...over,
  };
}

const form = (over: Partial<TraineeCallForm> = {}): TraineeCallForm => ({
  ...emptyCallForm(),
  ...over,
});

describe("walidacja formularza rozmowy", () => {
  it("B2B jest wymagane — pusty formularz nie przechodzi", () => {
    const result = validateCallForm(form());
    expect(result.ok).toBe(false);
    expect(result.errors.b2b).toMatch(/B2B/);
  });

  it("samo B2B wystarcza — reszta pól jest opcjonalna", () => {
    expect(validateCallForm(form({ b2b: "b2b" })).ok).toBe(true);
  });

  it("minimalna stawka musi być > 0 i liczbą", () => {
    expect(validateCallForm(form({ b2b: "b2b", rateValue: "0" })).errors.rate).toBeDefined();
    expect(validateCallForm(form({ b2b: "b2b", rateValue: "-5" })).errors.rate).toBeDefined();
    expect(validateCallForm(form({ b2b: "b2b", rateValue: "sto" })).errors.rate).toBeDefined();
    expect(validateCallForm(form({ b2b: "b2b", rateValue: "135,50" })).ok).toBe(true);
  });

  it("dni w biurze 0–5", () => {
    expect(validateCallForm(form({ b2b: "b2b", maxOnsiteDays: "6" })).errors.maxOnsiteDays).toBeDefined();
    expect(validateCallForm(form({ b2b: "b2b", maxOnsiteDays: "0" })).ok).toBe(true);
  });

  it("„tylko etat” nie wymaga niczego więcej, nawet przy błędnej stawce w ukrytym polu", () => {
    const f = form({ b2b: "employment_only", rateValue: "abc", maxOnsiteDays: "9" });
    expect(validateCallForm(f).ok).toBe(true);
  });
});

describe("ciało zapisu rozmowy", () => {
  it("mapuje pola na kontrakt API", () => {
    const body = toCallBody(
      form({
        b2b: "would_switch",
        rateValue: "1 400",
        rateUnit: "day",
        acceptsBelowMin: false,
        remoteModes: ["hybrid"],
        maxOnsiteDays: "2",
        officeCities: "Kraków; zdalnie z całej Polski",
        acceptsMoreOfficeDays: true,
        workTime: "also_part_time",
        availability: "within_1m",
        openToOffers: "yes",
        wants: "  bez bankowości  ",
      }),
    );
    expect(body).toEqual({
      b2b_willingness: "would_switch",
      min_rate: { value: 1400, unit: "day" },
      accepts_below_min_rate: false,
      remote_modes: ["hybrid"],
      max_onsite_days: 2,
      accepts_more_office_days: true,
      office_cities: ["Kraków", "zdalnie z całej Polski"],
      work_time_preference: "also_part_time",
      availability: "within_1m",
      open_to_offers: "yes",
      wants: "bez bankowości",
    });
  });

  it("puste pola dają null, nie zero ani pusty tekst", () => {
    const body = toCallBody(form({ b2b: "b2b" }));
    expect(body.min_rate).toBeNull();
    expect(body.max_onsite_days).toBeNull();
    expect(body.wants).toBeNull();
    expect(body.office_cities).toEqual([]);
  });

  it("„tylko etat” nie przemyca ukrytych pól", () => {
    const body = toCallBody(
      form({ b2b: "employment_only", rateValue: "150", remoteModes: ["remote"], wants: "x" }),
    );
    expect(body).toEqual({
      b2b_willingness: "employment_only",
      min_rate: null,
      accepts_below_min_rate: null,
      remote_modes: [],
      max_onsite_days: null,
      accepts_more_office_days: null,
      office_cities: [],
      work_time_preference: null,
      availability: null,
      open_to_offers: null,
      wants: null,
    });
  });

  it("bez B2B rzuca — najpierw walidacja", () => {
    expect(() => toCallBody(form())).toThrow();
  });

  it("parseRate czyta spacje i przecinek", () => {
    expect(parseRate("")).toBeNull();
    expect(parseRate("1 400")).toBe(1400);
    expect(parseRate("135,5")).toBe(135.5);
    expect(Number.isNaN(parseRate("12a") as number)).toBe(true);
  });

  it("przełączniki: ponowny klik zdejmuje wybór", () => {
    expect(toggleValue("b2b", "b2b")).toBeNull();
    expect(toggleValue<string>(null, "b2b")).toBe("b2b");
    expect(toggleInList(["remote"], "remote")).toEqual([]);
    expect(toggleInList(["remote"], "hybrid")).toEqual(["remote", "hybrid"]);
  });
});

describe("lista na dziś", () => {
  const now = new Date("2026-09-24T11:00:00Z");

  it("odłożeni po pierwszej próbie idą na koniec „Do zrobienia”, zamknięci osobno", () => {
    const items = [
      item(1, { retry_after: "2026-09-24T13:00:00Z", attempts: 1 }),
      item(2),
      item(3, { outcome: "call", closed_at: "2026-09-24T09:00:00Z" }),
      item(4),
    ];
    const { open, closed } = splitItems(items);
    expect(open.map((i) => i.id)).toEqual([2, 4, 1]);
    expect(closed.map((i) => i.id)).toEqual([3]);
  });

  it("następna osoba to pierwsza otwarta; czekającą na ponowny telefon bierzemy na końcu", () => {
    const items = [item(1), item(2, { retry_after: "2026-09-24T13:00:00Z" }), item(3)];
    expect(nextOpenItemId(items, 1, now)).toBe(3);
    expect(nextOpenItemId([item(1), item(2, { retry_after: "2026-09-24T13:00:00Z" })], 1, now)).toBe(2);
    expect(nextOpenItemId([item(1)], 1, now)).toBeNull();
  });

  it("etykieta ponownej próby wynika z retry_after (3 h po pierwszej)", () => {
    const label = retryLabel(item(1, { retry_after: "2026-09-24T12:00:00" }));
    expect(label).toBe("1. próba 09:00 — zadzwoń ponownie po 12:00");
    expect(retryLabel(item(2))).toBeNull();
  });

  it("liczniki liczone z pozycji — pierwsza próba bez odpowiedzi NIE zamyka pozycji", () => {
    const today: TraineeToday = {
      list_date: "2026-09-24",
      status: "ready",
      program: { day: 12, total_days: 40, status: "active" },
      counts: { total: 4, closed: 0, open: 4, call: 0, noanswer: 0, later: 0, wrong: 0, declined: 0 },
      day_completed: false,
      answered_pct: null,
      team_answered_pct: null,
      items: [
        item(1, { outcome: "call", closed_at: "x" }),
        item(2, { outcome: "noanswer", attempts: 1, retry_after: "y" }),
        item(3, { outcome: "noanswer", attempts: 2, closed_at: "x" }),
        item(4),
      ],
    };
    expect(recountToday(today).counts).toEqual({
      total: 4, closed: 2, open: 2, call: 1, noanswer: 1, later: 0, wrong: 0, declined: 0,
    });
  });

  it("braki mają polskie etykiety, nieznany kod nie wychodzi surowy", () => {
    expect(missingLabel("rate_stale")).toBe("stawka nieaktualna");
    expect(missingLabel("below_min_consent")).toBe("zgoda poniżej stawki?");
    expect(missingLabel("cos_nowego")).toBe("brak danych w profilu");
  });

  it("stawka w profilu: kwota, miesiąc i „nieaktualna”", () => {
    expect(profileRateLabel(item(1))).toBe("brak");
    const stale = item(2, {
      facts: { ...item(2).facts, min_rate_hourly: 140, rate_updated_at: "2025-03-10T00:00:00Z" },
      reasons: { fits: 1, open_fits: 0, stack: [], missing: ["rate_stale"] },
    });
    expect(profileRateLabel(stale)).toBe("140 zł/h — z 03.2025, nieaktualna");
  });

  it("dlaczego ta osoba", () => {
    expect(whyThisPerson({ fits: 6, open_fits: 2, stack: ["Java", "Kafka"], missing: [] })).toBe(
      "Pasuje do 6 rekrutacji z ostatnich 18 miesięcy (Java, Kafka). 2 z nich są otwarte teraz.",
    );
    expect(whyThisPerson({ fits: 3, open_fits: 0, stack: [], missing: [] })).toMatch(/Żadna nie jest dziś otwarta/);
  });

  it("link tel: bez spacji", () => {
    expect(telHref("+48 601 234 518")).toBe("tel:+48601234518");
    expect(telHref(null)).toBeNull();
  });

  it("pełny profil: „tylko etat” wystarcza, przy B2B potrzeba stawki, trybu, wymiaru i dostępności", () => {
    const base = item(1).facts;
    expect(isCompleteProfile({ ...base, b2b_willingness: "employment_only" })).toBe(true);
    expect(isCompleteProfile({ ...base, b2b_willingness: "b2b" })).toBe(false);
    expect(
      isCompleteProfile({
        ...base,
        b2b_willingness: "b2b",
        min_rate_hourly: 150,
        remote_modes: ["remote"],
        work_time_preference: "full_time_only",
        availability_status: "actively_looking",
      }),
    ).toBe(true);
  });
});

describe("telefon innego dnia", () => {
  it("następny dzień roboczy omija weekend", () => {
    expect(nextBusinessDay("2026-09-24")).toBe("2026-09-25"); // czwartek → piątek
    expect(nextBusinessDay("2026-09-25")).toBe("2026-09-28"); // piątek → poniedziałek
  });

  it("data musi być po dziś i nie w weekend", () => {
    expect(laterDateError("2026-09-24", "2026-09-24")).toMatch(/po dzisiejszym/);
    expect(laterDateError("2026-09-23", "2026-09-24")).toMatch(/po dzisiejszym/);
    expect(laterDateError("2026-09-26", "2026-09-24")).toMatch(/sobota/);
    expect(laterDateError("", "2026-09-24")).toBe("Wybierz datę.");
    expect(laterDateError("2026-09-28", "2026-09-24")).toBeNull();
    // Po końcu programu lista już nie powstanie — oddzwonienie by przepadło (R4-9).
    expect(laterDateError("2026-09-29", "2026-09-24", "2026-09-28")).toBe(
      "Wybierz dzień do końca programu (28.09.2026).",
    );
    expect(laterDateError("2026-09-28", "2026-09-24", "2026-09-28")).toBeNull();
    expect(laterDateError("2026-10-05", "2026-09-24", null)).toBeNull();
  });
});

describe("notatka dla rekrutera", () => {
  it("z formularza — same fakty z rozmowy", () => {
    const note = handoverNoteFromForm(
      form({
        b2b: "b2b",
        openToOffers: "yes",
        rateValue: "145",
        acceptsBelowMin: true,
        workTime: "also_part_time",
        remoteModes: ["hybrid"],
        maxOnsiteDays: "2",
        officeCities: "Kraków",
        acceptsMoreOfficeDays: false,
        availability: "within_1m",
        wants: "Nie chce bankowości.",
      }),
    );
    expect(note).toBe(
      "Szuka projektu. Pracuje na B2B. Minimum 145 zł/h netto B2B — przy niższym budżecie można dzwonić. " +
        "Full-time albo part-time. Tryb: hybrydowo, maks. 2 dni w biurze, dojazd: Kraków, więcej nie. " +
        "Może zacząć w ciągu miesiąca. Nie chce bankowości.",
    );
  });

  it("z faktów profilu, gdy rozmowa jest już zapisana", () => {
    const facts = {
      ...item(1).facts,
      b2b_willingness: "would_switch" as const,
      min_rate_hourly: 150,
      remote_modes: ["remote" as const],
    };
    expect(handoverNoteFromFacts(facts)).toBe(
      "Przejdzie z etatu na B2B. Minimum 150 zł/h netto B2B. Tryb: zdalnie.",
    );
  });
});
