/**
 * „Statystyki roczne" + „Analiza placementów" — sekcje `/insights` → Rekrutacja.
 *
 * Sześć reguł pod ochroną. Każda dotyczy tego, że wykres pokazuje co innego,
 * niż pokazuje liczba pod nim:
 *
 * 1. **Luka przerywa linię.** Miesiąc bez mianownika wraca jako `null`.
 *    Zszyty odcinkiem (albo podmieniony na 0) narysowałby pomiar, którego
 *    nikt nie wykonał — a spadek do zera czyta się jak zapaść zespołu.
 * 2. **Oś konwersji NIE MA sufitu 100%.** 200% jest sygnałem o kolejności
 *    etapów w danych z importu; przycięte do stu wygląda jak norma.
 * 3. **Dwie osie Y na wykresie progresu.** Bez prawej osi placementy leżą
 *    płasko przy zerze obok weryfikacji i wykres kłamie o zespole.
 * 4. **Awaria ≠ pustka.** 500 i 403 renderują się jako awaria, nigdy jako
 *    „nic się nie wydarzyło".
 * 5. **Donut sumuje się do kafla nad sobą.** Wiersze zbiorcze zostają
 *    w rozbiciu; zwijamy ogon, nie ucinamy go.
 * 6. **`null` udziału to „—", nie „0%".** Zero jest werdyktem, myślnik
 *    pytaniem.
 *
 * Asercje sięgają do realnej geometrii SVG (ścieżki serii, kreski osi,
 * wycinki donuta), bo recharts potrafi zamontować się bez błędu i narysować
 * PUSTY `<svg>` — sam render niczego nie dowodzi.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import {
  afterAll,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.get(...args) },
  api: { get: (...args: unknown[]) => mocks.get(...args) },
}));

import {
  collapseTail,
  InsightsPlacementAnalysis,
  sliceColor,
  type DonutSlice,
} from "@/components/insights/sections/InsightsPlacementAnalysis";
import {
  conversionAxisMax,
  InsightsYearlyStats,
} from "@/components/insights/sections/InsightsYearlyStats";
import type {
  PlacementAnalysisResponse,
  YearlyStatsResponse,
} from "@/lib/insights-charts-api";

const YEARLY_URL = "/api/insights/charts/yearly-stats";
const PLACEMENTS_URL = "/api/insights/charts/placement-analysis";

/**
 * `ResponsiveContainer` mierzy się przez `getBoundingClientRect()`, a jsdom
 * zawsze zwraca 0×0 — bez tego stubu recharts wyrenderowałby pusty kontener
 * i testy przechodziłyby na fałszywie pustym wykresie.
 *
 * Stub MUSI być zawężony do samego kontenera: podmiana globalna kłamie także
 * pomiarowi tekstu, z którego `YAxis` liczy szerokość — oś urosłaby wtedy do
 * szerokości wykresu i zjadła obszar rysowania.
 */
const REAL_RECT = Element.prototype.getBoundingClientRect;

beforeAll(() => {
  window.matchMedia = ((query: string) => ({
    matches: query.includes("prefers-reduced-motion"),
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;

  Element.prototype.getBoundingClientRect = function (this: Element) {
    if (this.classList?.contains("recharts-responsive-container")) {
      return {
        width: 800,
        height: 320,
        top: 0,
        left: 0,
        right: 800,
        bottom: 320,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      } as DOMRect;
    }
    return REAL_RECT.call(this);
  };
});

afterAll(() => {
  Element.prototype.getBoundingClientRect = REAL_RECT;
});

beforeEach(() => {
  mocks.get.mockReset();
});

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } });
}

function respond(url: string, value: unknown) {
  mocks.get.mockImplementation((requested: string) => {
    if (requested !== url) {
      return Promise.reject(
        new Error(`Nieoczekiwany URL w teście: ${requested}`),
      );
    }
    if (value instanceof Error) return Promise.reject(value);
    return Promise.resolve({ data: value });
  });
}

function renderWithClient(node: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{node}</QueryClientProvider>,
  );
}

const MONTH_LABELS = ["sty", "lut", "mar", "kwi"] as const;

const YEARLY: YearlyStatsResponse = {
  period: {
    kind: "year",
    start: "2026-01-01T00:00:00+01:00",
    end: "2027-01-01T00:00:00+01:00",
    timezone: "Europe/Warsaw",
  },
  year: 2026,
  months: MONTH_LABELS.map((label, i) => ({
    month: `2026-0${i + 1}-01`,
    label,
    is_partial: i === MONTH_LABELS.length - 1,
    verified: [800, 640, 910, 720][i],
    cv_sent: [400, 320, 455, 360][i],
    interview: [120, 96, 140, 110][i],
    hired: [30, 24, 35, 28][i],
    // Luka w lutym: mianownik w tym miesiącu był zerem.
    conv_verified_to_cv_sent: [50, null, 200, 50][i],
    conv_cv_sent_to_interview: [30, 30, 30.8, 30.6][i],
    conv_interview_to_hired: [25, 25, 25, 25.5][i],
    conv_verified_to_hired: [3.8, 3.8, 3.8, 3.9][i],
  })),
  series: [
    { key: "verified", label: "Weryfikacje", axis: "left" },
    { key: "cv_sent", label: "Rekomendacje", axis: "left" },
    { key: "interview", label: "Interviews", axis: "left" },
    { key: "hired", label: "Placements", axis: "right" },
  ],
  conversion_series: [
    { key: "conv_verified_to_cv_sent", label: "Weryfikacje → Rekomendacje" },
    { key: "conv_cv_sent_to_interview", label: "Rekomendacje → Interviews" },
    { key: "conv_interview_to_hired", label: "Interviews → Placements" },
    {
      key: "conv_verified_to_hired",
      label: "Overall (Weryfikacja → Placement)",
    },
  ],
  totals: { verified: 3070, cv_sent: 1535, interview: 466, hired: 117 },
};

const PLACEMENTS: PlacementAnalysisResponse = {
  period: {
    kind: "month",
    start: "2026-08-01T00:00:00+02:00",
    end: "2026-09-01T00:00:00+02:00",
    timezone: "Europe/Warsaw",
  },
  totals: {
    people: 2,
    placements: 10,
    clients: 2,
    unattributed_placements: 3,
    placements_without_job: 0,
  },
  by_person: [
    {
      user_id: 1,
      name: "Anna Kowalska",
      placements: 4,
      share_pct: 40,
      attributed: true,
    },
    {
      user_id: 2,
      name: "Jan Nowak",
      placements: 3,
      share_pct: 30,
      attributed: true,
    },
    {
      user_id: null,
      name: "(nieprzypisane)",
      placements: 3,
      share_pct: 30,
      attributed: false,
    },
  ],
  by_client: [
    {
      client_id: 7,
      name: "Bank Alfa",
      placements: 6,
      share_pct: 60,
      attributed: true,
    },
    {
      client_id: 8,
      name: "Telco Beta",
      placements: 4,
      share_pct: 40,
      attributed: true,
    },
  ],
  placements_definition: "first_hired_per_candidate_job",
};

function sectionOf(title: string): HTMLElement {
  const heading = screen.getByText(title);
  const section = heading.closest("section");
  if (!section) throw new Error(`Nagłówek „${title}" nie jest w <section>`);
  return section as HTMLElement;
}

function curvesIn(section: HTMLElement): SVGPathElement[] {
  return Array.from(
    section.querySelectorAll<SVGPathElement>("path.recharts-line-curve"),
  );
}

describe("InsightsYearlyStats — Progress zespołu", () => {
  it("rysuje cztery serie z realną geometrią i obie osie Y", async () => {
    respond(YEARLY_URL, YEARLY);
    renderWithClient(<InsightsYearlyStats year={2026} />);

    // Query jest asynchroniczne — bez `findBy` sięgalibyśmy po sekcję
    // w stanie ładowania i test mierzyłby spinner.
    await screen.findByText("Progress zespołu – 2026");
    const section = sectionOf("Progress zespołu – 2026");
    const curves = curvesIn(section);
    expect(curves).toHaveLength(4);
    curves.forEach((curve) => {
      const d = curve.getAttribute("d") ?? "";
      expect(d.startsWith("M")).toBe(true);
      expect(d.match(/[-\d.]+,[-\d.]+/g)?.length ?? 0).toBeGreaterThanOrEqual(
        4,
      );
    });

    // Reguła 3: dwie osie Y. Seria wskazująca `yAxisId`, którego nie ma
    // w wykresie, znika bez żadnego błędu — dlatego liczymy osie, nie ufamy
    // temu, że linia się narysowała.
    expect(section.querySelectorAll(".recharts-yAxis")).toHaveLength(2);
    expect(section.querySelectorAll(".recharts-xAxis")).toHaveLength(1);
    expect(
      section.querySelectorAll(".recharts-cartesian-grid line").length,
    ).toBeGreaterThan(0);

    // Legenda niesie etykiety z SERWERA — rozjazd nazwy z danymi jest
    // niewykrywalny wzrokiem, więc sprawdzamy, że nazwa w ogóle dociera.
    expect(within(section).getByText("Weryfikacje")).toBeInTheDocument();
    expect(within(section).getByText("Placements")).toBeInTheDocument();
    // Przypisanie osi jest napisane pod wykresem, nie tylko zakodowane.
    expect(
      within(section).getByText(/Placements — prawa oś/),
    ).toBeInTheDocument();
    // Miesiąc w toku podpisany, bo jego spadek nie jest wynikiem zespołu.
    expect(
      within(section).getByText(/Miesiąc „kwi” jeszcze trwa/),
    ).toBeInTheDocument();
  });
});

describe("InsightsYearlyStats — Efektywność lejka", () => {
  it("przerywa linię na luce i NIE przycina osi do 100%", async () => {
    respond(YEARLY_URL, YEARLY);
    renderWithClient(<InsightsYearlyStats year={2026} />);

    await screen.findByText("Efektywność lejka – 2026");
    const section = sectionOf("Efektywność lejka – 2026");
    const curves = curvesIn(section);
    expect(curves).toHaveLength(4);

    // Reguła 1: seria z luką ma ścieżkę PRZERWANĄ (drugie „M"), seria bez luki
    // — ciągłą. Sama liczba punktów tego nie pokaże: `connectNulls` zszywa
    // dziurę i zostawia tyle samo współrzędnych, tylko połączonych.
    const withGap = curves[0].getAttribute("d") ?? "";
    const withoutGap = curves[1].getAttribute("d") ?? "";
    expect((withGap.match(/M/g) ?? []).length).toBeGreaterThan(1);
    expect((withoutGap.match(/M/g) ?? []).length).toBe(1);

    // Reguła 2: oś sięga powyżej stu procent, bo dane sięgają 200%.
    //
    // Etykiety kresek osi NIE leżą w grupie `.recharts-yAxis` — recharts 3
    // renderuje je w osobnej warstwie z-index (`.recharts-yAxis-tick-labels`)
    // wewnątrz tego samego `<svg>`. Selektor „wewnątrz osi" zwracał pustą
    // listę, a `[].some(...)` to `false`, więc test padał na poprawnie
    // narysowanej osi. Asercja o niepustej liście jest tu po to, żeby kolejna
    // zmiana klas w rechartsie nie przebrała się za regresję w kodzie — ani
    // odwrotnie: żeby pusty selektor nie przepuścił przyciętej osi.
    const ticks = Array.from(
      section.querySelectorAll(
        ".recharts-yAxis-tick-labels .recharts-cartesian-axis-tick-value",
      ),
    ).map((t) =>
      Number((t.textContent ?? "").replace("%", "").replace(",", ".")),
    );
    expect(ticks.length).toBeGreaterThan(0);
    expect(ticks.some((t) => t > 100)).toBe(true);

    // Linia odniesienia 100% — bez niej przekroczenie stu nie rzuca się w oczy.
    expect(
      section.querySelector(".recharts-reference-line line"),
    ).not.toBeNull();

    expect(
      within(section).getByText(
        /Przerwa w linii to miesiąc z zerowym mianownikiem/,
      ),
    ).toBeInTheDocument();
    expect(
      within(section).getByText(/W tym roku takich punktów jest 1\./),
    ).toBeInTheDocument();
  }, 30000);

  it("podłoga osi to 100%, sufit rośnie z danymi", () => {
    expect(conversionAxisMax(12)).toBe(100);
    expect(conversionAxisMax(0)).toBe(100);
    expect(conversionAxisMax(200)).toBe(200);
    expect(conversionAxisMax(203)).toBe(210);
    // `-Infinity` to realny `dataMax` przy samych lukach — bez guardu oś
    // dostałaby NaN i zniknęła razem z wykresem.
    expect(conversionAxisMax(-Infinity)).toBe(100);
    expect(conversionAxisMax(NaN)).toBe(100);
  });
});

describe("InsightsYearlyStats — stany nie-danych", () => {
  it("awaria renderuje się jako awaria, nie jako brak danych", async () => {
    respond(YEARLY_URL, httpError(500));
    renderWithClient(<InsightsYearlyStats year={2026} />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText(/Brak miesięcy/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Spróbuj ponownie/ }),
    ).toBeInTheDocument();
  });

  it("403 mówi o uprawnieniach, a nie o pustych danych", async () => {
    respond(YEARLY_URL, httpError(403));
    renderWithClient(<InsightsYearlyStats year={2026} />);

    expect(
      await screen.findByText(/nie ma dostępu do sekcji/),
    ).toBeInTheDocument();
  });

  it("rok bez rozpoczętych miesięcy tłumaczy pustkę zamiast rysować zera", async () => {
    respond(YEARLY_URL, { ...YEARLY, year: 2099, months: [], totals: {} });
    renderWithClient(<InsightsYearlyStats year={2099} />);

    expect(
      await screen.findByText(/Brak miesięcy do pokazania/),
    ).toBeInTheDocument();
    expect(document.querySelectorAll("path.recharts-line-curve")).toHaveLength(
      0,
    );
  });
});

describe("InsightsPlacementAnalysis", () => {
  it("rysuje dwa donuty, trzy kafle i sumuje wycinki do kafla nad nimi", async () => {
    respond(PLACEMENTS_URL, PLACEMENTS);
    renderWithClient(
      <InsightsPlacementAnalysis period={{ period: "month", offset: -1 }} />,
    );

    expect(await screen.findByText("Placementy wg osób")).toBeInTheDocument();

    // Trzy kafle: kafel „Osoby" NIE liczy wiersza „(nieprzypisane)".
    expect(screen.getByText("Osoby z placementami")).toBeInTheDocument();
    expect(screen.getByText("Suma placementów")).toBeInTheDocument();
    expect(screen.getByText("Klienci")).toBeInTheDocument();
    expect(screen.getByText(/3 placementów bez autora/)).toBeInTheDocument();

    const peopleBox = screen.getByText("Placementy wg osób").parentElement!;
    const clientBox = screen.getByText("Placementy wg klientów").parentElement!;
    expect(peopleBox.querySelectorAll("path.recharts-sector")).toHaveLength(3);
    expect(clientBox.querySelectorAll("path.recharts-sector")).toHaveLength(2);

    // Reguła 5: wiersz bez atrybucji ZOSTAJE w legendzie donuta.
    expect(within(peopleBox).getByText("(nieprzypisane)")).toBeInTheDocument();
    expect(within(peopleBox).getByText("Anna Kowalska")).toBeInTheDocument();

    // Liczby bezwzględne wycinków — celowo `span.ml-auto`, a nie wszystkie
    // komórki `tabular-nums`: obok stoi kolumna udziału procentowego.
    const counts = Array.from(
      peopleBox.querySelectorAll("li span.ml-auto"),
    ).map((el) => Number((el.textContent ?? "").replace(/\s/g, "")));
    expect(counts).toHaveLength(PLACEMENTS.by_person.length);
    expect(counts.reduce((a, b) => a + b, 0)).toBe(
      PLACEMENTS.totals.placements,
    );
  });

  it("null udziału renderuje myślnik, nie zero procent", async () => {
    respond(PLACEMENTS_URL, {
      ...PLACEMENTS,
      by_person: [
        {
          user_id: 1,
          name: "Anna Kowalska",
          placements: 10,
          share_pct: null,
          attributed: true,
        },
      ],
    });
    renderWithClient(
      <InsightsPlacementAnalysis period={{ period: "month", offset: -1 }} />,
    );

    const peopleBox = (await screen.findByText("Placementy wg osób"))
      .parentElement!;
    expect(within(peopleBox).getByText("—")).toBeInTheDocument();
    expect(within(peopleBox).queryByText("0.0%")).not.toBeInTheDocument();
  }, 30000);

  it("puste okno to komunikat, a awaria to alert — nigdy odwrotnie", async () => {
    respond(PLACEMENTS_URL, {
      ...PLACEMENTS,
      totals: {
        people: 0,
        placements: 0,
        clients: 0,
        unattributed_placements: 0,
        placements_without_job: 0,
      },
      by_person: [],
      by_client: [],
    });
    const { unmount } = renderWithClient(
      <InsightsPlacementAnalysis period={{ period: "month", offset: -1 }} />,
    );
    expect(
      await screen.findByText("Brak placementów w wybranym oknie."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    unmount();

    respond(PLACEMENTS_URL, httpError(500));
    renderWithClient(
      <InsightsPlacementAnalysis period={{ period: "month", offset: -1 }} />,
    );
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.queryByText("Brak placementów w wybranym oknie."),
    ).not.toBeInTheDocument();
  });
});

describe("collapseTail — ogon donuta", () => {
  const slice = (i: number, placements: number): DonutSlice => ({
    id: i,
    name: `Klient ${i}`,
    placements,
    share_pct: 1,
    attributed: true,
  });

  it("nie rusza listy krótszej niż limit", () => {
    const rows = [slice(1, 5), slice(2, 3)];
    expect(collapseTail(rows, 8, 8)).toBe(rows);
  });

  it("zwija ogon ZACHOWUJĄC sumę", () => {
    const rows = Array.from({ length: 12 }, (_, i) => slice(i, 12 - i));
    const total = rows.reduce((s, r) => s + r.placements, 0);
    const collapsed = collapseTail(rows, total, 8);

    expect(collapsed).toHaveLength(9);
    expect(collapsed.at(-1)!.name).toBe("Pozostali (4)");
    // To jest cały sens tej funkcji: donut nadal sumuje się do kafla nad nim.
    expect(collapsed.reduce((s, r) => s + r.placements, 0)).toBe(total);
    // Koszyk nie jest osobą — nie wolno mu dostać koloru „prawdziwego" wycinka.
    expect(collapsed.at(-1)!.attributed).toBe(false);
    expect(sliceColor(collapsed.at(-1)!, 0)).toBe(
      "hsl(var(--muted-foreground))",
    );
    expect(sliceColor(collapsed[0], 0)).toBe("hsl(var(--chart-1))");
  });

  it("przy pustym oknie udział koszyka to null, nie 0%", () => {
    const rows = Array.from({ length: 10 }, (_, i) => slice(i, 0));
    expect(collapseTail(rows, 0, 8).at(-1)!.share_pct).toBeNull();
  });
});
