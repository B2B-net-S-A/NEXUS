/**
 * Model przycisku Ligi Mistrzów w górnym pasku i jego panelu.
 *
 * Czysta funkcja: przycisk, panel i harness `/preview/kpi-topbar` tylko go
 * rysują, więc każda reguła tekstu idzie tutaj i do testu modelu.
 *
 * - Rekruter: miejsce i punkty w Lidze rekruterów (bieżący kwartał).
 * - Delivery Lead: miejsce i hit ratio w Lidze DL — od 25.10.2026 ranking
 *   po hit ratio, bez punktów i bez nagród.
 * - Kto nie gra: kto prowadzi Ligę rekruterów i pierwsza piątka.
 *
 * Bez miejsca to nie zero, a „0 pkt” to nie awaria (awarię rysuje
 * `leagueErrorModel`). Reguły: docs/claude/ui/liga-w-gornym-pasku.md.
 */

import type { LeagueRow, LeagueStanding, MyLeague } from "@/lib/insights-races-api";
import { countPl, pluralPl } from "@/lib/plural-pl";

export type LeagueMedalTone = "gold" | "silver" | "bronze" | "neutral" | "warn" | "off" | "error";

export interface LeagueMedal {
  /** Numer miejsca albo „–”; `null` = ikona awarii. */
  text: string | null;
  tone: LeagueMedalTone;
}

export interface LeagueSentence {
  text: string;
  tone: "default" | "good" | "warn";
}

export interface LeagueBreakdownRow {
  label: string;
  detail: string;
  points: string;
}

export interface LeaguePanelRow {
  key: string;
  rank: string;
  rankTone: "gold" | "silver" | "bronze" | "plain";
  name: string;
  value: string;
  /** Nagroda miejsca na podium albo „remis”; `null` poza podium. */
  prize: string | null;
  me: boolean;
}

export interface LeaguePanelModel {
  title: string;
  aside: string | null;
  medal: LeagueMedal;
  headline: string;
  headlineValue: string | null;
  sub: string | null;
  sentences: LeagueSentence[];
  breakdown: { rows: LeagueBreakdownRow[]; total: string } | null;
  condition: { met: boolean; text: string } | null;
  rowsTitle: string | null;
  rowsUnit: string | null;
  rows: LeaguePanelRow[];
  footnote: string | null;
  link: { href: string; label: string } | null;
  /** Awaria zapytania — panel pokazuje „Ponów”. */
  failed: boolean;
}

export interface LeagueTopbarModel {
  medal: LeagueMedal;
  /** Górna linia: liga i stan („Liga · Q4”, „Liga · bez miejsca”, „Liga · prowadzi”). */
  label: string;
  /** Dolna linia: sam wynik („385 pkt”, „4 placementy”, „Marta W.”). */
  value: string;
  /** Awans od pierwszego widoku dnia („z 6.”). */
  up: string | null;
  /** Nazwa przycisku dla czytnika ekranu — całe zdanie, niezależnie od okna. */
  spoken: string;
  panel: LeaguePanelModel;
}

export interface LeagueModelOptions {
  /** Miejsce z pierwszego widoku dnia (`league-rank-memory`). */
  baselineRank?: number | null;
}

export const LEAGUE_LINK = { href: "/insights?tab=rywalizacja", label: "Cała liga" } as const;

/** Rozmów u klienta nie podajemy jako drogi, gdy byłoby ich więcej. */
const MAX_INTERVIEWS_AS_PATH = 20;

const PODIUM = 3;

/** „1240”, „12 400” — zapis liczb jak w reszcie aplikacji (pl-PL). */
export function formatLeagueNumber(value: number): string {
  return value.toLocaleString("pl-PL");
}

function points(value: number): string {
  return `${formatLeagueNumber(value)} pkt`;
}

function spokenPoints(value: number): string {
  return countPl(value, "punkt", "punkty", "punktów");
}

/** Dopełniacz po „brakuje”: 1 punktu, 2 punktów, 5 punktów. */
function spokenPointsMissing(value: number): string {
  return countPl(value, "punktu", "punktów", "punktów");
}

function placements(value: number): string {
  return countPl(value, "placement", "placementy", "placementów");
}

/** Dopełniacz po „brakuje”: 1 placementu, 2 placementów, 5 placementów. */
function placementsMissing(value: number): string {
  return countPl(value, "placementu", "placementów", "placementów");
}

/** „Marta W.” — imię i inicjał nazwiska; pojedyncze słowo bez zmian. */
export function shortName(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length < 2) return parts[0] ?? "";
  return `${parts[0]} ${parts[parts.length - 1].charAt(0)}.`;
}

function quarterOf(period: string): string {
  return period.split(" ")[0] || period;
}

function medalTone(rank: number): LeagueMedalTone {
  if (rank === 1) return "gold";
  if (rank === 2) return "silver";
  if (rank === 3) return "bronze";
  return "neutral";
}

function rankTone(rank: number | null): LeaguePanelRow["rankTone"] {
  if (rank === 1) return "gold";
  if (rank === 2) return "silver";
  if (rank === 3) return "bronze";
  return "plain";
}

function daysAside(days: number): string {
  if (days <= 0) return "ostatni dzień kwartału";
  return `do końca ${countPl(days, "dzień", "dni", "dni")}`;
}

function podiumPrizes(prizes: Record<string, number>): string | null {
  const values = [1, 2, 3].map((rank) => prizes[String(rank)]);
  if (values.some((value) => typeof value !== "number")) return null;
  return `podium: ${values.map(formatLeagueNumber).join(" / ")} zł`;
}

function leagueSub(data: MyLeague): string | null {
  const people = `${countPl(data.total, "osoba", "osoby", "osób")} w lidze`;
  const prizes = podiumPrizes(data.prizes_pln);
  return prizes ? `${people} · ${prizes}` : people;
}

/**
 * Czym nadrobić dystans w punktach: najwyżej dwie drogi, krótsza pierwsza.
 * „To 1 placement albo 6 rozmów u klienta.” Rozmów powyżej 20 nie podajemy.
 */
export function workToClose(
  gap: number,
  formula: MyLeague["points_formula"] | undefined,
): string | null {
  if (!formula || gap <= 0) return null;
  const options: string[] = [];
  if (formula.placement > 0) {
    options.push(placements(Math.ceil(gap / formula.placement)));
  }
  if (formula.interview > 0) {
    const interviews = Math.ceil(gap / formula.interview);
    if (interviews <= MAX_INTERVIEWS_AS_PATH) {
      options.push(countPl(interviews, "rozmowa u klienta", "rozmowy u klienta", "rozmów u klienta"));
    }
  }
  return options.length ? `To ${options.join(" albo ")}.` : null;
}

function panelRows(
  rows: readonly LeagueRow[],
  meId: number | null,
  formatValue: (row: LeagueRow) => string,
): LeaguePanelRow[] {
  return rows.map((row) => {
    const onPodium = row.rank !== null && row.rank <= PODIUM;
    let prize: string | null = null;
    if (onPodium && row.tied) prize = "remis";
    else if (onPodium && row.prize_pln) prize = `${formatLeagueNumber(row.prize_pln)} zł`;
    return {
      key: String(row.user_id),
      rank: row.rank !== null ? `${row.rank}.` : "–",
      rankTone: rankTone(row.rank),
      name: row.user_id === meId ? "Ty" : row.name,
      value: formatValue(row),
      prize,
      me: row.user_id === meId,
    };
  });
}

function upArrow(rank: number | null, baseline: number | null | undefined): string | null {
  if (rank === null || baseline === null || baseline === undefined) return null;
  return rank < baseline ? `z ${baseline}.` : null;
}

/**
 * O które miejsce jest remis. Z grupy remisu (`tie_for`): pozycje remisu
 * kończą się na podium, więc przy remisie 3. i 4. miejsca flagę `tied` ma
 * tylko 3., a przy remisie 1. i 2. osoba z 2. miejsca walczy o 1.
 * Flaga wiersza to zapas dla odpowiedzi sprzed tego pola.
 */
function tieFor(standing: LeagueStanding, rank: number | null): number | null {
  if (standing.tie_for !== undefined && standing.tie_for !== null) return standing.tie_for;
  return standing.me?.tied && rank !== null ? rank : null;
}

/** Zdania o dystansie dla osoby z miejscem — wspólne dla obu lig. */
function placedSentences(
  standing: LeagueStanding,
  rank: number,
  describe: { missing: (gap: number) => string; amount: (gap: number) => string },
  work: (gap: number) => string | null,
): LeagueSentence[] {
  const sentences: LeagueSentence[] = [];
  const tie = tieFor(standing, rank);
  if (tie !== null) {
    sentences.push({
      text: `Remis o ${tie}. miejsce. Jeśli zostanie do końca kwartału, rozstrzygnie admin.`,
      tone: "warn",
    });
  }
  if (rank === 1) {
    if (tie === null) {
      sentences.push({
        text:
          standing.lead_over_next !== null
            ? `Prowadzisz. Przewaga nad 2. miejscem: ${describe.amount(standing.lead_over_next)}.`
            : "Prowadzisz.",
        tone: "good",
      });
    }
    return sentences;
  }
  const gap = rank <= PODIUM ? standing.gap_to_place_above : standing.gap_to_podium;
  if (gap !== null && gap > 0) {
    const target = rank <= PODIUM ? `${rank - 1}. miejsca` : "podium";
    sentences.push({ text: `Do ${target} brakuje ${describe.missing(gap)}.`, tone: "default" });
    const path = work(gap);
    if (path) sentences.push({ text: path, tone: "default" });
  }
  if (rank <= PODIUM && standing.lead_over_next !== null && standing.lead_over_next > 0) {
    sentences.push({
      text: `Przewaga nad ${rank + 1}. miejscem: ${describe.amount(standing.lead_over_next)}.`,
      tone: "default",
    });
  }
  return sentences;
}

/** Dystans dla czytnika ekranu: „Do podium brakuje 85 punktów.” */
function spokenGap(standing: LeagueStanding, rank: number | null): string | null {
  if (rank === null || rank <= 1) return null;
  const gap = rank <= PODIUM ? standing.gap_to_place_above : standing.gap_to_podium;
  if (gap === null || gap <= 0) return null;
  const target = rank <= PODIUM ? `${rank - 1}. miejsca` : "podium";
  return `Do ${target} brakuje ${spokenPointsMissing(gap)}.`;
}

function thresholdLine(byMonth: readonly number[] | undefined): string | null {
  if (!byMonth || byMonth.length !== 3) return null;
  const [first, second, last] = byMonth;
  return `Próg w kolejnych miesiącach kwartału: ${first}, ${second} i ${last} ${pluralPl(last, "placement", "placementy", "placementów")}.`;
}

function recruiterModel(data: MyLeague, standing: LeagueStanding, options: LeagueModelOptions): LeagueTopbarModel {
  const quarter = quarterOf(data.period);
  const me = standing.me;
  const rank = standing.rank;
  const value = standing.value;
  const formula = data.points_formula;
  const required = data.required_placements ?? null;
  const myPlacements = me?.placements ?? 0;
  const up = upArrow(rank, options.baselineRank);

  let medal: LeagueMedal;
  let label = `Liga · ${quarter}`;
  let headline: string;
  let spokenState: string;
  let sentences: LeagueSentence[];

  if (me === null) {
    medal = { text: "–", tone: "off" };
    headline = "Jeszcze bez punktów";
    spokenState = "jeszcze bez punktów";
    sentences = formula
      ? [
          {
            text: `Pierwsze punkty: CV wysłane do klienta ${formula.recommendation}, rozmowa u klienta ${formula.interview}, placement ${formula.placement}.`,
            tone: "default",
          },
        ]
      : [];
  } else if (rank === null) {
    medal = { text: "–", tone: "warn" };
    label = "Liga · bez miejsca";
    headline = "Bez miejsca";
    spokenState = `${spokenPoints(value)}, bez miejsca w klasyfikacji`;
    sentences = [
      {
        text:
          required !== null
            ? `Punkty się liczą. Miejsce w klasyfikacji dostaniesz, gdy będziesz mieć ${placements(required)} w kwartale.`
            : "Punkty się liczą. Miejsce w klasyfikacji dostaniesz po spełnieniu warunku udziału.",
        tone: "warn",
      },
    ];
    if (standing.position_by_value !== null) {
      sentences.push({ text: `Po punktach to ${standing.position_by_value}. pozycja.`, tone: "default" });
    }
  } else {
    medal = { text: String(rank), tone: medalTone(rank) };
    if (tieFor(standing, rank) !== null) label = "Liga · remis";
    headline = `${rank}. miejsce`;
    spokenState = `${rank}. miejsce, ${spokenPoints(value)}`;
    sentences = placedSentences(standing, rank, { missing: points, amount: points }, (gap) =>
      workToClose(gap, formula),
    );
  }

  if (up) sentences.unshift({ text: `Dziś awans z ${options.baselineRank}. na ${rank}. miejsce.`, tone: "good" });

  const breakdown =
    me && formula && me.placements !== undefined && me.interviews !== undefined && me.recommendations !== undefined
      ? {
          rows: [
            {
              label: "Placementy",
              detail: `${me.placements} × ${formula.placement}`,
              points: formatLeagueNumber(me.placements * formula.placement),
            },
            {
              label: "Rozmowy u klienta",
              detail: `${me.interviews} × ${formula.interview}`,
              points: formatLeagueNumber(me.interviews * formula.interview),
            },
            {
              label: "CV wysłane do klienta",
              detail: `${me.recommendations} × ${formula.recommendation}`,
              points: formatLeagueNumber(me.recommendations * formula.recommendation),
            },
          ],
          total: formatLeagueNumber(value),
        }
      : null;

  let condition: LeaguePanelModel["condition"] = null;
  if (required !== null) {
    const threshold = thresholdLine(data.required_placements_by_month);
    const met = myPlacements >= required;
    const head = met
      ? "Warunek spełniony."
      : `Do warunku brakuje ${placementsMissing(required - myPlacements)} w kwartale.`;
    condition = { met, text: threshold ? `${head} ${threshold}` : head };
  }

  const gapForReader = spokenGap(standing, rank);
  return {
    medal,
    label,
    value: points(value),
    up,
    spoken:
      `Liga Mistrzów, ${data.period}: ${spokenState}.` +
      (gapForReader ? ` ${gapForReader}` : "") +
      (up ? ` Dziś awans z ${options.baselineRank}. miejsca.` : ""),
    panel: {
      title: `Liga Mistrzów · ${data.period}`,
      aside: daysAside(data.days_remaining),
      medal,
      headline,
      headlineValue: points(value),
      sub: leagueSub(data),
      sentences,
      breakdown,
      condition,
      rowsTitle: standing.neighbours.length ? "Obok Ciebie" : null,
      rowsUnit: standing.neighbours.length ? "pkt" : null,
      rows: panelRows(standing.neighbours, me?.user_id ?? null, (row) => formatLeagueNumber(row.metric_value)),
      footnote: "Punkty liczą się osobie, która zweryfikowała kandydata.",
      link: LEAGUE_LINK,
      failed: false,
    },
  };
}

/** „36,4%”, bez zbędnego „,0”; `null` = hit ratio niepoliczone. */
export function formatHitRatio(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value.toLocaleString("pl-PL", { maximumFractionDigits: 1 })}%`;
}

/** Dystans w lidze DL po „brakuje”: „5,3 punktu procentowego”, „2 punktów procentowych”. */
function hitRatioPointsMissing(gap: number): string {
  if (!Number.isInteger(gap)) return `${gap.toLocaleString("pl-PL")} punktu procentowego`;
  return countPl(gap, "punktu procentowego", "punktów procentowych", "punktów procentowych");
}

/** Przewaga w lidze DL: „6,4 punktu procentowego”, „2 punkty procentowe”. */
function hitRatioPoints(gap: number): string {
  if (!Number.isInteger(gap)) return `${gap.toLocaleString("pl-PL")} punktu procentowego`;
  return countPl(gap, "punkt procentowy", "punkty procentowe", "punktów procentowych");
}

/** „Brakuje 1 placementu i 2 zamkniętych rekrutacji.” albo `null`, gdy warunek spełniony. */
function dlMissingSentence(dl: NonNullable<MyLeague["dl"]>): string | null {
  const parts: string[] = [];
  if (dl.missing_placements > 0) parts.push(placementsMissing(dl.missing_placements));
  const closed = dl.missing_closed_requests ?? 0;
  if (closed > 0) {
    parts.push(countPl(closed, "zamkniętej rekrutacji", "zamkniętych rekrutacji", "zamkniętych rekrutacji"));
  }
  return parts.length ? `Brakuje ${parts.join(" i ")}.` : null;
}

/**
 * Liga DL od 25.10.2026: ranking po hit ratio, miejsce od 3 placementów
 * i 5 zamkniętych rekrutacji, bez nagród. `standing.value` i dystanse są
 * w procentach (backend: `league_standing(value_key="hit_ratio")`).
 */
function deliveryLeadModel(data: MyLeague, standing: LeagueStanding, options: LeagueModelOptions): LeagueTopbarModel {
  const quarter = quarterOf(data.period);
  const dl = data.dl;
  const me = standing.me;
  const rank = standing.rank;
  const hitRatio = me ? (me.hit_ratio ?? null) : (dl?.hit_ratio ?? null);
  const hitValue = formatHitRatio(hitRatio);
  const up = upArrow(rank, options.baselineRank);
  const minPlacements = dl?.min_placements ?? 3;
  const minClosed = dl?.min_closed_requests ?? 5;

  const hitLine =
    dl && dl.hit_ratio !== null
      ? `Hit ratio ${formatHitRatio(dl.hit_ratio)} (${dl.placements} z ${dl.closed_requests} ${pluralPl(dl.closed_requests, "zamkniętej rekrutacji", "zamkniętych rekrutacji", "zamkniętych rekrutacji")}).`
      : "Hit ratio liczy się od pierwszej rekrutacji zamkniętej w kwartale.";
  // 21.10.2026: duplikaty, anulowane przez klienta i obsadzone wewnętrznie nie
  // wchodzą do hit ratio — zdanie mówi, ile ich było, żeby liczby się zgadzały.
  const neutral = dl?.closed_neutral ?? 0;
  const neutralLine =
    neutral > 0
      ? ` ${pluralPl(neutral, "Jedna zamknięta nie liczy się", `${neutral} zamknięte nie liczą się`, `${neutral} zamkniętych nie liczy się`)} (duplikat, anulowana, wewnętrzna…).`
      : "";
  const hitText = hitLine + neutralLine;

  let medal: LeagueMedal;
  let label = `Liga DL · ${quarter}`;
  let headline: string;
  let spokenState: string;
  let sentences: LeagueSentence[];

  if (me !== null && rank !== null) {
    medal = { text: String(rank), tone: medalTone(rank) };
    headline = `${rank}. miejsce`;
    spokenState = `${rank}. miejsce, hit ratio ${hitValue}`;
    sentences = [
      ...placedSentences(standing, rank, { missing: hitRatioPointsMissing, amount: hitRatioPoints }, () => null),
      { text: hitText, tone: "default" },
    ];
  } else if (me !== null) {
    medal = { text: "–", tone: "warn" };
    label = "Liga DL · bez miejsca";
    headline = "Bez miejsca";
    spokenState = `hit ratio ${hitValue}, bez miejsca w klasyfikacji`;
    sentences = [{ text: hitText, tone: "default" }];
    if (standing.position_by_value !== null) {
      sentences.push({ text: `Po hit ratio to ${standing.position_by_value}. pozycja.`, tone: "default" });
    }
  } else {
    medal = { text: "–", tone: "off" };
    headline = "Jeszcze bez wyniku";
    spokenState = "jeszcze bez wyniku";
    sentences = [{ text: hitText, tone: "default" }];
  }

  if (up) sentences.unshift({ text: `Dziś awans z ${options.baselineRank}. na ${rank}. miejsce.`, tone: "good" });

  const missing = dl ? dlMissingSentence(dl) : null;
  const condition: LeaguePanelModel["condition"] = dl
    ? {
        met: dl.qualified,
        text: dl.qualified
          ? `Warunek spełniony: co najmniej ${placements(minPlacements)} i ${minClosed} zamkniętych rekrutacji.`
          : `Miejsce w klasyfikacji od ${placementsMissing(minPlacements)} i ${minClosed} zamkniętych rekrutacji w kwartale.${missing ? ` ${missing}` : ""}`,
      }
    : null;

  return {
    medal,
    label,
    value: hitValue,
    up,
    spoken:
      `Liga Mistrzów DL, ${data.period}: ${spokenState}.` + (up ? ` Dziś awans z ${options.baselineRank}. miejsca.` : ""),
    panel: {
      title: `Liga Mistrzów DL · ${data.period}`,
      aside: daysAside(data.days_remaining),
      medal,
      headline,
      headlineValue: `${hitValue} hit ratio`,
      sub: leagueSub(data),
      sentences,
      breakdown: null,
      condition,
      rowsTitle: standing.neighbours.length ? "Obok Ciebie" : null,
      rowsUnit: standing.neighbours.length ? "hit ratio" : null,
      rows: panelRows(standing.neighbours, me?.user_id ?? null, (row) => formatHitRatio(row.hit_ratio)),
      footnote:
        "Liga DL to statystyka bez nagród: hit ratio = placementy w portfelu ÷ rekrutacje zamknięte w kwartale.",
      link: LEAGUE_LINK,
      failed: false,
    },
  };
}

function spectatorModel(data: MyLeague): LeagueTopbarModel | null {
  const leaders = data.leaders ?? [];
  const leader = leaders[0];
  if (!leader) return null;
  const medal: LeagueMedal = { text: "1", tone: "gold" };
  const name = shortName(leader.name);
  return {
    medal,
    label: leader.tied ? "Liga · remis o 1." : "Liga · prowadzi",
    value: name,
    up: null,
    spoken: `Liga Mistrzów, ${data.period}: prowadzi ${leader.name}, ${spokenPoints(leader.metric_value)}.`,
    panel: {
      title: `Liga Mistrzów · ${data.period}`,
      aside: daysAside(data.days_remaining),
      medal,
      headline: `Prowadzi ${name}`,
      headlineValue: points(leader.metric_value),
      sub: leagueSub(data),
      sentences: leader.tied
        ? [{ text: "Remis o 1. miejsce. Jeśli zostanie do końca kwartału, rozstrzygnie admin.", tone: "warn" }]
        : [],
      breakdown: null,
      condition: null,
      rowsTitle: "Pierwsza piątka",
      rowsUnit: "pkt",
      rows: panelRows(leaders, null, (row) => formatLeagueNumber(row.metric_value)),
      footnote: "Punkty dają placementy, rozmowy u klienta i CV wysłane do klienta.",
      link: LEAGUE_LINK,
      failed: false,
    },
  };
}

/** Model przycisku z odpowiedzi `/my-league`; `null` = nic do pokazania. */
export function buildLeagueTopbarModel(
  data: MyLeague,
  options: LeagueModelOptions = {},
): LeagueTopbarModel | null {
  if (data.kind === "spectator") return spectatorModel(data);
  if (!data.standing) return null;
  if (data.kind === "delivery_lead") return deliveryLeadModel(data, data.standing, options);
  return recruiterModel(data, data.standing, options);
}

/** Awaria zapytania: „—”, nigdy „0 pkt”. */
export function leagueErrorModel(): LeagueTopbarModel {
  const medal: LeagueMedal = { text: null, tone: "error" };
  return {
    medal,
    label: "Liga",
    value: "—",
    up: null,
    spoken: "Liga Mistrzów: nie udało się wczytać.",
    panel: {
      title: "Liga Mistrzów",
      aside: null,
      medal,
      headline: "Nie udało się wczytać ligi",
      headlineValue: null,
      sub: null,
      sentences: [{ text: "Spróbuj jeszcze raz. Ranking jest też w Insights → Rywalizacja.", tone: "default" }],
      breakdown: null,
      condition: null,
      rowsTitle: null,
      rowsUnit: null,
      rows: [],
      footnote: null,
      link: LEAGUE_LINK,
      failed: true,
    },
  };
}
