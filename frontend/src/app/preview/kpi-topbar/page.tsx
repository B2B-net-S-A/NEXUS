"use client";

/**
 * Harness licznika celów w górnym pasku — publiczny, ZERO zapytań.
 *
 * Rysuje prezentacyjne części (`KpiTopbarButton`, `KpiGoalsPanel`) na danych
 * fikcyjnych. Paski na górze to repliki powłoki na całą szerokość okna: atrapa
 * menu (240 px od 1280 px, niżej szyna 60 px) i pasek z tymi samymi klasami co
 * `TopbarV2` — tak, żeby przy 1280 × 720 dało się zmierzyć, ile miejsca
 * zostaje wyszukiwarce. Sąsiedzi licznika mają prawdziwe rozmiary (ikony
 * „Czaty” i „Rozmowy” to prawdziwe komponenty prezentacyjne), a licznik
 * w paskach to ten sam komponent co w aplikacji (klik otwiera panel).
 *
 * Od 13.10.2026 przed licznikiem stoi przycisk Ligi Mistrzów (prawdziwy
 * `LeagueTopbarPopover` na danych fikcyjnych), a trzy przełączniki wyglądu
 * zastąpiło jedno menu „Wygląd” — jak w `TopbarV2`.
 */

import { Plus, Search, Users } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { KpiGoalsPanel } from "@/components/v2/kpi/KpiGoalsPanel";
import { KpiTopbarButton } from "@/components/v2/kpi/KpiTopbarButton";
import { KpiTopbarPopover } from "@/components/v2/kpi/MyKpiWidget";
import { buildKpiTopbarModel, type KpiTopbarModel } from "@/components/v2/kpi/kpi-topbar-model";
import { LeaguePanel } from "@/components/v2/league/LeaguePanel";
import { LeagueTopbarButton } from "@/components/v2/league/LeagueTopbarButton";
import { LeagueTopbarPopover } from "@/components/v2/league/MyLeagueWidget";
import {
  LEAGUE_DL_NO_CLOSED,
  LEAGUE_DL_SECOND,
  LEAGUE_DL_UNPLACED,
  LEAGUE_RECRUITER_FOURTH,
  LEAGUE_RECRUITER_LEADER,
  LEAGUE_RECRUITER_SECOND,
  LEAGUE_RECRUITER_TIED,
  LEAGUE_RECRUITER_UNQUALIFIED,
  LEAGUE_RECRUITER_ZERO,
  LEAGUE_SPECTATOR,
} from "@/components/v2/league/league-fixtures";
import {
  buildLeagueTopbarModel,
  leagueErrorModel,
  type LeagueTopbarModel,
} from "@/components/v2/league/league-topbar-model";
import { ChatTopbarButton } from "@/components/v2/shell/ChatNotificationsDropdown";
import { CvTopbarButton } from "@/components/v2/shell/CvNotificationsDropdown";
import { JobsTopbarButton } from "@/components/v2/shell/JobsNotificationsDropdown";
import { InterviewsTopbarButton } from "@/components/v2/shell/InterviewNotificationsDropdown";
import { AppearanceMenu } from "@/components/v2/shell/AppearanceMenu";
import {
  TOPBAR_ACTIONS_CLASS,
  TOPBAR_BREADCRUMB_CLASS,
  TOPBAR_HEADER_CLASS,
  TOPBAR_SEARCH_CLASS,
} from "@/components/v2/shell/topbar-layout";
import type { KpiGoal, KpiResult, KpiState, MyKpiGoals } from "@/lib/api";
import { cn } from "@/lib/utils";

// ── Dane fikcyjne ───────────────────────────────────────────────────────────

interface RecruiterDay {
  verifications: [current: number, state: KpiState, expected: number];
  recommendations: [current: number, state: KpiState, expected: number];
  placements: [current: number, state: KpiState];
  hoursLeft: number;
}

function recruiter(day: RecruiterDay): KpiResult[] {
  const [verifications, verificationsState, verificationsExpected] = day.verifications;
  const [recommendations, recommendationsState, recommendationsExpected] = day.recommendations;
  const [placements, placementsState] = day.placements;
  return [
    {
      kpi_id: "daily_first_verifications",
      period: "day",
      title_pl: "Weryfikacje dziś",
      short_title_pl: "Weryfikacje",
      description_pl: "Liczy się pierwsze przejście kandydata na „Zweryfikowany”.",
      target: 4,
      current: verifications,
      progress_pct: (verifications / 4) * 100,
      state: verificationsState,
      deadline_hours_left: day.hoursLeft,
      expected_count: verificationsExpected,
    },
    {
      kpi_id: "weekly_cvs_sent",
      period: "week",
      title_pl: "Rekomendacje w tygodniu",
      short_title_pl: "Rekomendacje",
      description_pl: "Liczy się pierwsza wysyłka CV kandydata do klienta.",
      target: 15,
      current: recommendations,
      progress_pct: (recommendations / 15) * 100,
      state: recommendationsState,
      deadline_hours_left: 80,
      expected_count: recommendationsExpected,
    },
    {
      kpi_id: "monthly_placements",
      period: "month",
      title_pl: "Placementy w tym miesiącu",
      short_title_pl: "Placementy",
      description_pl: "Liczy się pierwsze zatrudnienie kandydata.",
      target: 1,
      current: placements,
      progress_pct: placements * 100,
      state: placementsState,
      deadline_hours_left: 400,
      expected_count: 0.4,
    },
  ];
}

function teamGoal(partial: Partial<KpiGoal> & Pick<KpiGoal, "goal_id" | "short_title_pl">): KpiGoal {
  return {
    title_pl: `${partial.short_title_pl} zespołu`,
    period: "day",
    unit: "count",
    target: 48,
    current: 31,
    progress_pct: 64.6,
    state: "ahead",
    note: "Suma celów osób z tym celem: 12",
    ...partial,
  };
}

const TEAM: MyKpiGoals = {
  kind: "team",
  scope_label: "Zespół rekrutacji",
  people: 12,
  goals: [
    teamGoal({ goal_id: "team_daily_first_verifications", short_title_pl: "Weryfikacje", expected: 24 }),
    teamGoal({
      goal_id: "team_weekly_cvs_sent",
      short_title_pl: "Rekomendacje",
      period: "week",
      target: 180,
      current: 41,
      state: "behind",
      expected: 54,
    }),
    teamGoal({
      goal_id: "team_monthly_placements",
      short_title_pl: "Placementy",
      period: "month",
      target: 12,
      current: 5,
      state: "on_track",
      expected: 4.6,
    }),
    teamGoal({
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

/** Delivery Lead: cel placementów to 30% rekrutacji zamkniętych w kwartale, w górę. */
function deliveryLead(placements: number, closed: number): MyKpiGoals {
  const target = Math.ceil((closed * 30) / 100);
  const state: KpiState | null = closed === 0 ? null : placements >= target ? "hit" : "behind";
  return {
    kind: "delivery_lead",
    scope_label: "Q4 2026",
    people: null,
    closed_requests: closed,
    own_handoffs: { verified: 5, cv_sent: 3, hired: 1 },
    goals: [
      {
        goal_id: "dl_hit_ratio_quarter",
        title_pl: "Hit ratio portfela w kwartale",
        short_title_pl: "Hit ratio",
        period: "quarter",
        unit: "pct",
        target: 30,
        current: closed === 0 ? null : Math.round((1000 * placements) / closed) / 10,
        progress_pct: null,
        state,
        note:
          closed === 0
            ? "Niepoliczony — w tym kwartale nie zamknięto żadnej rekrutacji w Twoim portfelu."
            : null,
      },
      {
        goal_id: "dl_placements_quarter",
        title_pl: "Placementy portfela w kwartale",
        short_title_pl: "Placementy",
        period: "quarter",
        unit: "count",
        target,
        current: placements,
        progress_pct: null,
        state,
        note:
          closed === 0
            ? "Cel pojawi się po zamknięciu pierwszej rekrutacji w kwartale."
            : `Rekrutacje zamknięte w kwartale: ${closed}`,
      },
    ],
  };
}

function model(kpis: KpiResult[], goals: MyKpiGoals | null): KpiTopbarModel {
  const built = buildKpiTopbarModel(kpis, goals);
  if (!built) throw new Error("Harness: brak danych do licznika celów.");
  return built;
}

// Wtorek 13:15 — połowa dnia roboczego (9:00–17:30).
const RECRUITER_MIDDAY = model(
  recruiter({
    verifications: [1, "behind", 2],
    recommendations: [6, "ahead", 4.5],
    placements: [0, "on_track"],
    hoursLeft: 4.25,
  }),
  null,
);
const HEAD = model([], TEAM);
const DELIVERY_LEAD = model([], deliveryLead(2, 10));
const DELIVERY_LEAD_EMPTY = model([], deliveryLead(2, 0));

function league(data: Parameters<typeof buildLeagueTopbarModel>[0], baselineRank: number | null = null): LeagueTopbarModel {
  const built = buildLeagueTopbarModel(data, { baselineRank });
  if (!built) throw new Error("Harness: dane fikcyjne bez modelu ligi");
  return built;
}

const LEAGUE_RECRUITER = league(LEAGUE_RECRUITER_FOURTH);
const LEAGUE_HEAD = league(LEAGUE_SPECTATOR);
const LEAGUE_DL = league(LEAGUE_DL_UNPLACED);

const LEAGUE_STATES: { title: string; note: string; model: LeagueTopbarModel }[] = [
  { title: "Lider", note: "złote kółko, w panelu przewaga nad 2. miejscem", model: league(LEAGUE_RECRUITER_LEADER) },
  { title: "Podium", note: "srebro; dystans do 1. miejsca", model: league(LEAGUE_RECRUITER_SECOND) },
  { title: "Poza podium", note: "od 4. miejsca dystans do podium", model: LEAGUE_RECRUITER },
  { title: "Awans dziś", note: "strzałka do północy; spadek bez strzałki", model: league(LEAGUE_RECRUITER_FOURTH, 6) },
  { title: "Remis", note: "remis o płatne miejsce rozstrzyga admin", model: league(LEAGUE_RECRUITER_TIED) },
  { title: "Bez miejsca", note: "punkty są, warunek udziału nie", model: league(LEAGUE_RECRUITER_UNQUALIFIED) },
  { title: "Bez punktów", note: "też 1. dnia kwartału", model: league(LEAGUE_RECRUITER_ZERO) },
  { title: "Awaria", note: "„—”, nigdy „0 pkt”", model: leagueErrorModel() },
  { title: "DL z miejscem", note: "liga DL po hit ratio, bez nagród", model: league(LEAGUE_DL_SECOND) },
  { title: "DL bez miejsca", note: "w panelu, czego brakuje do miejsca", model: LEAGUE_DL },
  { title: "DL bez zamkniętych", note: "hit ratio niepoliczone", model: league(LEAGUE_DL_NO_CLOSED) },
  { title: "Kto nie gra", note: "HoR, TCM, admin, Finanse", model: LEAGUE_HEAD },
];

const DAY_STATES: { title: string; note: string; model: KpiTopbarModel }[] = [
  {
    title: "Przed 9:00",
    note: "Nic nie jest oceniane — same liczby.",
    model: model(
      recruiter({
        verifications: [0, "on_track", 0],
        recommendations: [3, "on_track", 3],
        placements: [0, "on_track"],
        hoursLeft: 8.5,
      }),
      null,
    ),
  },
  {
    title: "10:00, 1 z 4",
    note: "W tempie: bez znaczka (do 13.10 ten wynik dostawał tarczę).",
    model: model(
      recruiter({
        verifications: [1, "ahead", 0.5],
        recommendations: [3, "on_track", 3.4],
        placements: [0, "on_track"],
        hoursLeft: 7.5,
      }),
      null,
    ),
  },
  { title: "13:15, 1 z 4", note: "Poniżej tempa: brakuje całej sztuki.", model: RECRUITER_MIDDAY },
  {
    title: "15:40, 4 z 4",
    note: "Cel zrobiony: zielony znaczek.",
    model: model(
      recruiter({
        verifications: [4, "hit", 3.1],
        recommendations: [7, "ahead", 4.8],
        placements: [0, "on_track"],
        hoursLeft: 1.8,
      }),
      null,
    ),
  },
  {
    title: "Po 17:30, 3 z 4",
    note: "Dzień zamknięty: wyszarzony wynik, bez krzyżyka.",
    model: model(
      recruiter({
        verifications: [3, "missed", 4],
        recommendations: [7, "on_track", 6],
        placements: [0, "on_track"],
        hoursLeft: 0,
      }),
      null,
    ),
  },
  {
    title: "Piątek, komplet",
    note: "Wynik ponad cel zostaje liczbą (5 z 4).",
    model: model(
      recruiter({
        verifications: [5, "hit", 4],
        recommendations: [15, "hit", 15],
        placements: [1, "hit"],
        hoursLeft: 0.5,
      }),
      null,
    ),
  },
];

// ── Replika powłoki ─────────────────────────────────────────────────────────

function ShellStrip({
  title,
  breadcrumb,
  model: stripModel,
  league: leagueModel,
  callPill = false,
}: {
  title: string;
  breadcrumb: string;
  model: KpiTopbarModel;
  league: LeagueTopbarModel;
  /** Ikona „Rozmowy” jako pigułka „zadzwoń po rozmowie” — najszerszy stan sąsiada. */
  callPill?: boolean;
}) {
  return (
    <section aria-label={title} data-testid="shell-strip">
      <h2 className="px-4 pb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground sm:px-6">
        {title}
      </h2>
      <div className="flex border-y border-border">
        {/* Menu jak w `SidebarV2`: 240 px od 1280 px (domyślne przypięcie), niżej szyna. */}
        <div
          aria-hidden="true"
          className="hidden w-[60px] shrink-0 border-r border-border bg-sidebar md:block xl:w-60"
        />
        <div className={cn(TOPBAR_HEADER_CLASS, "min-w-0 flex-1")} data-testid="topbar-replica">
          <div className={TOPBAR_BREADCRUMB_CLASS}>
            <span className="truncate text-sm font-medium text-foreground">{breadcrumb}</span>
          </div>
          <div className={TOPBAR_SEARCH_CLASS} data-testid="topbar-search">
            <Search className="h-4 w-4 shrink-0" aria-hidden />
            <span className="truncate">Szukaj kandydatów, rekrutacji, klientów…</span>
            <div className="ml-auto hidden shrink-0 items-center gap-1 sm:flex">
              <Kbd>Ctrl</Kbd>
              <Kbd>K</Kbd>
            </div>
          </div>
          <div className={TOPBAR_ACTIONS_CLASS}>
            <LeagueTopbarPopover model={leagueModel} className="hidden md:block" />
            <KpiTopbarPopover model={stripModel} className="hidden md:block" />
            <div className="hidden items-center sm:flex">
              <AppearanceMenu />
            </div>
            <Button variant="ghost" size="icon" aria-label="Moi ludzie (atrapa)">
              <Users className="h-4 w-4" aria-hidden />
            </Button>
            {/* Ikona „CV” (16.10.2026, dawna pigułka „Do wysłania”) — w replice zawsze
                jako pigułka, żeby pomiar paska brał najszerszy układ (pigułka nie
                kurczy się, oddaje licznik celów). */}
            <CvTopbarButton badge={12} urgency="late" />
            <JobsTopbarButton unreadJobs={4} open={false} />
            <ChatTopbarButton unreadThreads={0} hasMention={false} open={false} />
            <InterviewsTopbarButton
              count={callPill ? 2 : 0}
              urgent={callPill}
              open={false}
              pill={callPill ? { name: "A. Przykładowa", minutesLeft: 18 } : null}
            />
            <Button size="sm" variant="primary">
              <Plus className="h-4 w-4" aria-hidden />
              <span className="hidden sm:inline">Dodaj</span>
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}

function LeaguePanelFrame({ title, model: panelModel }: { title: string; model: LeagueTopbarModel }) {
  return (
    <section className="w-full max-w-[360px] shrink-0">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
      <div className="overflow-hidden rounded-lg border border-border bg-card shadow-md" role="dialog" aria-label={title}>
        <LeaguePanel model={panelModel} />
      </div>
    </section>
  );
}

function PanelFrame({ title, model: panelModel }: { title: string; model: KpiTopbarModel }) {
  return (
    <section className="w-full max-w-[360px] shrink-0">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
      <div className="overflow-hidden rounded-lg border border-border bg-card shadow-md" role="dialog" aria-label={title}>
        <KpiGoalsPanel model={panelModel} />
      </div>
    </section>
  );
}

export default function KpiTopbarPreviewPage() {
  return (
    <main className="min-h-dvh bg-muted/30 pb-10">
      <div className="p-4 sm:p-6">
        <h1 className="mb-1 text-lg font-semibold text-foreground">Licznik celów w górnym pasku — harness</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Podpisane segmenty zamiast trzech par „znak + liczba”, znaczek tylko przy wyjątku, szczegóły
          w panelu po kliknięciu. Dane fikcyjne, bez zapytań do serwera. Licznik pokazuje tyle całych
          segmentów, ile mieści pasek (wyszukiwarka ma gwarantowane 220 px); poniżej 1024 px słowo „Cele”,
          forma zwarta do 1535 px, od 1536 pełna. Przed licznikiem przycisk Ligi Mistrzów, który się nie
          ściska; motyw, tryb gry i tryb ciemny są w menu „Wygląd”.
        </p>
      </div>

      <div className="flex flex-col gap-5">
        <ShellStrip
          title="Rekruter — wtorek 13:15"
          breadcrumb="Rekrutacje › Senior Java Developer"
          model={RECRUITER_MIDDAY}
          league={LEAGUE_RECRUITER}
        />
        <ShellStrip
          title="Head of Recruitment i TCM — zespół 12 osób"
          breadcrumb="Pulpit"
          model={HEAD}
          league={LEAGUE_HEAD}
        />
        {/* Najszerszy przycisk ligi (DL poza ligą, 163 px): HoR z rolą DL ma cele zespołu i ligę DL. */}
        <ShellStrip
          title="Head of Recruitment z rolą DL — najciaśniej: długie okruszki i pigułka „Rozmowy”"
          breadcrumb="Rekrutacje › Senior Java Developer z Kafką i Springiem (Warszawa, hybryda)"
          model={HEAD}
          league={LEAGUE_DL}
          callPill
        />
        <ShellStrip
          title="Delivery Lead — 10 zamkniętych rekrutacji, 2 placementy"
          breadcrumb="Pulpit"
          model={DELIVERY_LEAD}
          league={LEAGUE_DL}
        />
      </div>

      <div className="p-4 sm:p-6">
        <h2 className="mb-3 text-sm font-semibold text-foreground">Stany w ciągu dnia</h2>
        <ul className="flex flex-col gap-3">
          {DAY_STATES.map((dayState) => (
            <li key={dayState.title} className="flex flex-wrap items-center gap-x-4 gap-y-1">
              <span className="w-32 shrink-0 text-sm font-medium text-foreground">{dayState.title}</span>
              <KpiTopbarButton model={dayState.model} open={false} />
              <span className="text-xs text-muted-foreground">{dayState.note}</span>
            </li>
          ))}
        </ul>

        <h2 className="mb-3 mt-8 text-sm font-semibold text-foreground">Liga Mistrzów — stany przycisku</h2>
        <ul className="flex flex-col gap-3" data-testid="league-states">
          {LEAGUE_STATES.map((leagueState) => (
            <li key={leagueState.title} className="flex flex-wrap items-center gap-x-4 gap-y-1">
              <span className="w-32 shrink-0 text-sm font-medium text-foreground">{leagueState.title}</span>
              <LeagueTopbarButton model={leagueState.model} open={false} />
              <span className="text-xs text-muted-foreground">{leagueState.note}</span>
            </li>
          ))}
        </ul>

        <h2 className="mb-3 mt-8 text-sm font-semibold text-foreground">Liga Mistrzów — panel po kliknięciu</h2>
        <div className="flex flex-wrap items-start gap-6">
          <LeaguePanelFrame title="Liga — rekruter na 4. miejscu" model={LEAGUE_RECRUITER} />
          <LeaguePanelFrame title="Liga — bez miejsca" model={league(LEAGUE_RECRUITER_UNQUALIFIED)} />
          <LeaguePanelFrame title="Liga — Delivery Lead poza ligą" model={LEAGUE_DL} />
          <LeaguePanelFrame title="Liga — kto nie gra" model={LEAGUE_HEAD} />
        </div>

        <h2 className="mb-3 mt-8 text-sm font-semibold text-foreground">Panel po kliknięciu</h2>
        <div className="flex flex-wrap items-start gap-6">
          <PanelFrame title="Rekruter" model={RECRUITER_MIDDAY} />
          <PanelFrame title="Head of Recruitment i TCM" model={HEAD} />
          <PanelFrame title="Delivery Lead" model={DELIVERY_LEAD} />
          <PanelFrame title="Delivery Lead bez zamkniętych rekrutacji" model={DELIVERY_LEAD_EMPTY} />
        </div>
      </div>
    </main>
  );
}
