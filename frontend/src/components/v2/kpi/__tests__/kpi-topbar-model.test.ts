import { describe, expect, it } from "vitest";

import { buildKpiTopbarModel } from "@/components/v2/kpi/kpi-topbar-model";
import type { KpiGoal, KpiResult, MyKpiGoals } from "@/lib/api";

function kpi(partial: Partial<KpiResult> & Pick<KpiResult, "kpi_id">): KpiResult {
  return {
    period: "day",
    title_pl: "Tytuł z okresem",
    description_pl: "Opis.",
    target: 4,
    current: 0,
    progress_pct: 0,
    state: "on_track",
    deadline_hours_left: 4.25,
    ...partial,
  };
}

const VERIFICATIONS = kpi({
  kpi_id: "daily_first_verifications",
  title_pl: "Weryfikacje dziś",
  short_title_pl: "Weryfikacje",
  description_pl: "Liczy się pierwsze przejście kandydata na „Zweryfikowany”.",
  current: 1,
  target: 4,
  state: "behind",
  expected_count: 2,
});
const CALLS = kpi({
  kpi_id: "daily_completed_calls",
  title_pl: "Rozmowy dziś",
  short_title_pl: "Rozmowy",
  current: 3,
  target: 15,
});
const RECOMMENDATIONS = kpi({
  kpi_id: "weekly_cvs_sent",
  period: "week",
  title_pl: "Rekomendacje w tygodniu",
  short_title_pl: "Rekomendacje",
  current: 6,
  target: 15,
  expected_count: 4.5,
});
const PLACEMENTS = kpi({
  kpi_id: "monthly_placements",
  period: "month",
  title_pl: "Placementy w tym miesiącu",
  short_title_pl: "Placementy",
  current: 0,
  target: 1,
  expected_count: 0.4,
});

function goal(partial: Partial<KpiGoal> & Pick<KpiGoal, "goal_id">): KpiGoal {
  return {
    title_pl: "Cel",
    period: "day",
    unit: "count",
    target: 48,
    current: 31,
    progress_pct: 64.6,
    state: "on_track",
    note: "Suma celów osób z tym celem: 12",
    ...partial,
  };
}

function teamGoals(): MyKpiGoals {
  return {
    kind: "team",
    scope_label: "Zespół rekrutacji",
    people: 12,
    goals: [
      goal({ goal_id: "team_daily_first_verifications", short_title_pl: "Weryfikacje", expected: 24 }),
      goal({
        goal_id: "team_weekly_cvs_sent",
        short_title_pl: "Rekomendacje",
        period: "week",
        target: 180,
        current: 41,
        state: "behind",
        expected: 54,
      }),
      goal({
        goal_id: "team_monthly_placements",
        short_title_pl: "Placementy",
        period: "month",
        target: 12,
        current: 5,
        expected: 4.6,
      }),
      goal({
        goal_id: "team_monthly_precision",
        short_title_pl: "Precyzja",
        period: "month",
        unit: "pct",
        target: 75,
        current: 64.5,
        state: "behind",
        note: "Rekomendacje / weryfikacje (30 dni): 40 / 62",
      }),
    ],
  };
}

function dlGoals(overrides: { placements?: number; closed?: number | null } = {}): MyKpiGoals {
  const closed = overrides.closed === undefined ? 10 : overrides.closed;
  const placements = overrides.placements ?? 2;
  const counted = closed !== null && closed > 0;
  const target = counted ? Math.ceil((closed * 30) / 100) : 0;
  const state = counted ? (placements >= target ? "hit" : "behind") : null;
  return {
    kind: "delivery_lead",
    scope_label: "Q4 2026",
    people: null,
    closed_requests: closed,
    goals: [
      goal({
        goal_id: "dl_hit_ratio_quarter",
        title_pl: "Hit ratio portfela w kwartale",
        short_title_pl: "Hit ratio",
        period: "quarter",
        unit: "pct",
        target: 30,
        current: counted ? Math.round((1000 * placements) / closed) / 10 : null,
        state,
        note: counted ? null : "Niepoliczony — w tym kwartale nie zamknięto żadnej rekrutacji w Twoim portfelu.",
      }),
      goal({
        goal_id: "dl_placements_quarter",
        title_pl: "Placementy portfela w kwartale",
        short_title_pl: "Placementy",
        period: "quarter",
        target,
        current: placements,
        state,
        note: counted
          ? `Rekrutacje zamknięte w kwartale: ${closed}`
          : "Cel pojawi się po zamknięciu pierwszej rekrutacji w kwartale.",
      }),
    ],
  };
}

describe("licznik celów — rekruter", () => {
  it("nic do pokazania → brak modelu", () => {
    expect(buildKpiTopbarModel([], null)).toBeNull();
    expect(
      buildKpiTopbarModel([], { kind: "none", scope_label: "", people: null, goals: [] }),
    ).toBeNull();
  });

  it("trzy segmenty w stałej kolejności: dzień, tydzień, miesiąc — z nazwami", () => {
    // Kolejność z API bywa dowolna; do 13.10.2026 decydował alfabet po id.
    const model = buildKpiTopbarModel([PLACEMENTS, RECOMMENDATIONS, VERIFICATIONS], null);
    expect(model?.segments.map((s) => [s.label, s.value, s.rest, s.restCompact])).toEqual([
      ["Weryfikacje", "1", "/ 4 dziś", "/ 4 dziś"],
      ["Rekomendacje", "6", "/ 15 tydzień", "/ 15 tydz."],
      ["Placementy", "0", "/ 1 miesiąc", "/ 1 mies."],
    ]);
    expect(model?.lead).toBeNull();
  });

  it("czwarty cel (rozmowy przy włączonej telefonii) zostaje w panelu, nie wypycha placementów", () => {
    const model = buildKpiTopbarModel([CALLS, VERIFICATIONS, RECOMMENDATIONS, PLACEMENTS], null);
    expect(model?.segments.map((s) => s.label)).toEqual(["Weryfikacje", "Rekomendacje", "Placementy"]);
    const today = model?.groups.find((g) => g.id === "day");
    expect(today?.rows.map((r) => r.title)).toEqual(["Weryfikacje", "Rozmowy"]);
  });

  it("znaczek tylko przy wyjątku: poniżej tempa, zrobione, okres zamknięty", () => {
    const model = buildKpiTopbarModel(
      [
        VERIFICATIONS,
        { ...RECOMMENDATIONS, current: 15, state: "hit" },
        { ...PLACEMENTS, state: "ahead" },
      ],
      null,
    );
    expect(model?.segments.map((s) => s.mark)).toEqual(["behind", "hit", null]);
    const closed = buildKpiTopbarModel([{ ...VERIFICATIONS, current: 3, state: "missed" }], null);
    expect(closed?.segments[0].mark).toBe("missed");
  });

  it("panel: grupy po okresie, kreska tempa, zdanie o stanie i „co się liczy”", () => {
    const model = buildKpiTopbarModel([VERIFICATIONS, RECOMMENDATIONS, PLACEMENTS], null);
    expect(model?.panelTitle).toBe("Twoje cele");
    expect(model?.groups.map((g) => g.heading)).toEqual(["Dziś", "Ten tydzień", "Ten miesiąc"]);
    expect(model?.groups[0].aside).toBe("do końca dnia pracy: 4 h 15 min");

    const [verifications] = model!.groups[0].rows;
    expect(verifications).toMatchObject({
      value: "1",
      rest: "/ 4",
      progressPct: 25,
      expectedPct: 50,
      status: "Poniżej tempa (na tę godzinę: 2).",
      description: "Liczy się pierwsze przejście kandydata na „Zweryfikowany”.",
    });
    expect(model!.groups[1].rows[0]).toMatchObject({ status: "W tempie.", expectedPct: 30 });
    // Cel 1 nie ma tempa: bez kreski i bez oceny w środku miesiąca.
    expect(model!.groups[2].rows[0]).toMatchObject({
      status: "Cel na cały miesiąc, bez tempa.",
      expectedPct: null,
    });
    expect(model?.link).toEqual({ href: "/insights?tab=moj-miesiac", label: "Mój miesiąc" });
  });

  it("po końcu dnia pracy: „dzień zamknięty” zamiast odliczania", () => {
    const model = buildKpiTopbarModel(
      [{ ...VERIFICATIONS, current: 3, state: "missed", deadline_hours_left: 0 }],
      null,
    );
    expect(model?.groups[0].aside).toBe("dzień pracy zamknięty");
    expect(model?.groups[0].rows[0].status).toBe("Dzień zamknięty.");
    expect(model?.groups[0].rows[0].expectedPct).toBeNull();
  });

  it("odpowiedź sprzed wdrożenia backendu (bez nowych pól) ma zapas z tytułu", () => {
    const legacy = kpi({ kpi_id: "daily_first_verifications", title_pl: "Weryfikacje dziś", current: 1, state: "behind" });
    const model = buildKpiTopbarModel([legacy], null);
    expect(model?.segments[0].label).toBe("Weryfikacje dziś");
    expect(model?.groups[0].rows[0]).toMatchObject({ status: "Poniżej tempa.", expectedPct: null });
  });

  it("nazwa dla czytnika ekranu mówi to samo co segmenty", () => {
    const model = buildKpiTopbarModel([VERIFICATIONS, RECOMMENDATIONS, PLACEMENTS], null);
    expect(model?.spoken).toBe(
      "Twoje cele: Weryfikacje 1 z 4 dziś, poniżej tempa; Rekomendacje 6 z 15 tydzień; Placementy 0 z 1 miesiąc",
    );
  });
});

describe("licznik celów — Head of Recruitment i TCM", () => {
  it("te same trzy cele jako suma zespołu, z podpisem czyje; precyzja tylko w panelu", () => {
    const model = buildKpiTopbarModel([], teamGoals());
    expect(model?.lead).toBe("Zespół");
    expect(model?.panelAside).toBe("12 osób");
    expect(model?.segments.map((s) => [s.label, s.value, s.rest, s.mark])).toEqual([
      ["Weryfikacje", "31", "/ 48 dziś", null],
      ["Rekomendacje", "41", "/ 180 tydzień", "behind"],
      ["Placementy", "5", "/ 12 miesiąc", null],
    ]);
    expect(model?.panelTitle).toBe("Cele zespołu");
    const month = model?.groups.find((g) => g.id === "month");
    expect(month?.rows.map((r) => [r.title, r.value, r.rest])).toEqual([
      ["Placementy", "5", "/ 12"],
      ["Precyzja", "64,5%", "/ 75%"],
    ]);
    expect(month?.rows[1].description).toBe("Rekomendacje / weryfikacje (30 dni): 40 / 62");
    expect(model?.link?.href).toBe("/insights?tab=zespol");
  });

  it("precyzja poniżej 5 weryfikacji jest „niepoliczona”, nigdy zerem", () => {
    const goals = teamGoals();
    goals.goals[3] = { ...goals.goals[3], current: null, state: null, progress_pct: null, note: "Niepoliczony — mniej niż 5 weryfikacji w 30 dni." };
    const precision = buildKpiTopbarModel([], goals)?.groups.find((g) => g.id === "month")?.rows[1];
    expect(precision).toMatchObject({ value: "niepoliczony", rest: "", progressPct: null, status: null });
  });

  it("osoba z własnymi celami i celami lidera: w pasku osobiste, cele lidera w panelu", () => {
    const model = buildKpiTopbarModel([VERIFICATIONS, RECOMMENDATIONS, PLACEMENTS], teamGoals());
    expect(model?.lead).toBeNull();
    expect(model?.segments.map((s) => s.value)).toEqual(["1", "6", "0"]);
    expect(model?.groups.at(-1)?.heading).toBe("Cele zespołu · 12 osób");
  });
});

describe("licznik celów — Delivery Lead", () => {
  it("przykład Artura: 10 zamkniętych rekrutacji = cel 3 placementy", () => {
    const model = buildKpiTopbarModel([], dlGoals({ placements: 2, closed: 10 }));
    // Kolejność = ważność: w ciasnym pasku segmenty znikają od końca.
    expect(model?.segments.map((s) => [s.label, s.labelCompact, s.value, s.rest, s.mark])).toEqual([
      ["Placementy", "Placementy", "2", "/ 3", "behind"],
      // Oba wiersze to ten sam warunek — znaczek świeci raz, przy placementach.
      ["Hit ratio", "Hit ratio", "20%", "/ 30%", null],
      ["Zamknięte rekrutacje", "Zamknięte", "10", "w Q4", null],
    ]);
    expect(model?.panelTitle).toBe("Cel portfela");
    expect(model?.panelAside).toBe("Q4 2026");

    const [placements, hitRatio] = model!.groups[0].rows;
    expect(placements).toMatchObject({
      status: "Brakuje 1 placementu.",
      description: "Cel to 30% z 10 zamkniętych rekrutacji.",
      expectedPct: null,
    });
    expect(placements.progressPct).toBeCloseTo(66.7, 1);
    // Pasek hit ratio to skala 0–100% z kreską na progu 30%.
    expect(hitRatio).toMatchObject({
      progressPct: 20,
      expectedPct: 30,
      description: "2 placementy z 10 zamkniętych rekrutacji. Kreska to próg 30%.",
    });
    expect(model?.facts).toEqual([{ label: "Zamknięte rekrutacje w kwartale", value: "10" }]);
    // 21.10.2026: zamknięcia „nie liczy się” jako osobny fakt, tylko gdy są.
    const withNeutral = buildKpiTopbarModel([], {
      ...dlGoals({ placements: 2, closed: 10 }),
      closed_neutral: 2,
    });
    expect(withNeutral?.facts).toEqual([
      { label: "Zamknięte rekrutacje w kwartale", value: "10" },
      { label: "Zamknięte, które nie liczą się do hit ratio", value: "2" },
    ]);
    expect(model?.link?.href).toBe("/insights?tab=raporty&report=portfele-dl");
  });

  it("cel zrobiony i brakujące placementy w liczbie mnogiej", () => {
    const done = buildKpiTopbarModel([], dlGoals({ placements: 3, closed: 10 }));
    expect(done?.segments[0].mark).toBe("hit");
    expect(done?.groups[0].rows[0].status).toBe("Cel zrobiony.");
    const far = buildKpiTopbarModel([], dlGoals({ placements: 1, closed: 20 }));
    expect(far?.groups[0].rows[0].status).toBe("Brakuje 5 placementów.");
  });

  it("bez zamkniętych rekrutacji: sam wynik i notatka, nigdy „2/0” ani zero procent", () => {
    const model = buildKpiTopbarModel([], dlGoals({ placements: 2, closed: 0 }));
    expect(model?.segments.map((s) => [s.label, s.value, s.rest, s.mark])).toEqual([
      ["Placementy", "2", "", null],
      ["Hit ratio", "—", "/ 30%", null],
      ["Zamknięte rekrutacje", "0", "w Q4", null],
    ]);
    const [placements, hitRatio] = model!.groups[0].rows;
    expect(placements).toMatchObject({
      rest: "",
      progressPct: null,
      status: null,
      description: "Cel pojawi się po zamknięciu pierwszej rekrutacji w kwartale.",
    });
    expect(hitRatio).toMatchObject({ value: "niepoliczony", progressPct: null });
  });

  it("odpowiedź sprzed wdrożenia backendu (bez `closed_requests`): dwa segmenty", () => {
    const goals = dlGoals();
    delete goals.closed_requests;
    const model = buildKpiTopbarModel([], goals);
    expect(model?.segments.map((s) => s.label)).toEqual(["Placementy", "Hit ratio"]);
    expect(model?.facts).toEqual([]);
  });
});

describe("licznik celów — lista „Kto się liczy” (17.10.2026)", () => {
  function rowsById(model: ReturnType<typeof buildKpiTopbarModel>) {
    return Object.fromEntries(
      (model?.groups ?? []).flatMap((group) => group.rows).map((row) => [row.id, row]),
    );
  }

  it("własne cele z wynikiem mają link na listę w Mój miesiąc", () => {
    const rows = rowsById(buildKpiTopbarModel([VERIFICATIONS, RECOMMENDATIONS, CALLS], null));
    expect(rows.weekly_cvs_sent.link).toEqual({
      href: "/insights?tab=moj-miesiac&kto=rekomendacje#kto-sie-liczy",
      label: "Zobacz, kto się liczy",
    });
    expect(rows.daily_first_verifications.link?.href).toBe(
      "/insights?tab=moj-miesiac&kto=weryfikacje#kto-sie-liczy",
    );
    // Rozmowy telefoniczne to nie kamień kandydata — bez listy.
    expect(rows.daily_completed_calls.link).toBeNull();
  });

  it("zero nie ma linku — nie ma czego pokazać", () => {
    const rows = rowsById(buildKpiTopbarModel([PLACEMENTS, { ...RECOMMENDATIONS, current: 0 }], null));
    expect(rows.monthly_placements.link).toBeNull();
    expect(rows.weekly_cvs_sent.link).toBeNull();
  });

  it("cele zespołu i portfela nie mają linku", () => {
    const team = rowsById(buildKpiTopbarModel([], teamGoals()));
    expect(Object.values(team).every((row) => row.link === null)).toBe(true);
    const lead = rowsById(buildKpiTopbarModel([], dlGoals()));
    expect(Object.values(lead).every((row) => row.link === null)).toBe(true);
  });
});
