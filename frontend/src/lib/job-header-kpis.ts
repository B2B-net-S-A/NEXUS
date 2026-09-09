/**
 * Klaster trzech KPI w jobbarze rekrutacji (makieta „flow w języku C2", k2–k8).
 *
 * Jobbar jest wspólny dla kroków 02–08, ale liczby po jego prawej stronie NIE
 * są wspólne: każdy krok odpowiada na inne pytanie („kto utknął" na Pipeline,
 * „kto czeka na akceptację" w Screeningu, „kto ma weto HM" w Rozmowach). Ten
 * moduł jest tą mapą i niczym więcej — nie renderuje i nie woła sieci, więc
 * da się go przetestować na wartościach zamiast na zrzucie ekranu.
 *
 * ## `null` znaczy „jeszcze nie wiem", nigdy „zero"
 *
 * Kanban ładuje się osobnym zapytaniem, a ranking C2 bywa tylko w cache'u.
 * Dopóki ich nie ma, KPI ma wartość `null` i widok rysuje „—". Zero w tym
 * miejscu byłoby zdaniem o rekrutacji („nikogo tu nie ma"), którego nikt nie
 * sprawdził — dokładnie ta sama reguła, którą liczniki na listwie kroków
 * trzymają od kroku 05 (`pipelineCount` i spółka w `JobDetailCompactHeader`).
 *
 * ## Zero źródeł własnych
 *
 * Wszystko liczy się z TEGO SAMEGO kanbana, którym strona karmi listwę kroków,
 * i z cache'u zapytania rankingu. Żadne z tych KPI nie dokłada zapytania.
 */

import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";
import type { JobDetailTab } from "@/components/v2/jobs/JobDetailCompactHeader";
import {
  ACCEPTANCE_STAGE,
  CV_SENT_STAGE,
  countContractSent,
  countContractStages,
  countExternal,
  countHired,
  countHmVeto,
  countInProcess,
  countStage,
  countStalled,
  selectPendingVerifications,
  selectScreeningQueue,
  selectVerifiedQueue,
} from "@/lib/pipeline-flow";

/** Ton liczby — WYŁĄCZNIE nazwy semantyczne, kolory dobiera warstwa widoku. */
export type JobHeaderKpiTone = "neutral" | "ok" | "warn" | "bad";

export interface JobHeaderKpi {
  /** Stabilny klucz Reacta — etykiety powtarzają się między krokami. */
  key: string;
  label: string;
  /** `null` = nie policzono jeszcze (widok rysuje „—", nie 0). */
  value: number | null;
  tone: JobHeaderKpiTone;
}

/**
 * Próg „mocnego" dopasowania.
 *
 * Ta sama granica, na której pierścień wyniku w kanbanie robi się zielony
 * (`scoreRingColor` w `kanban-shared`). Gdyby jobbar liczył „≥ 75 pkt" wg
 * innego progu niż ten, po którym rekruter rozpoznaje mocne trafienie na
 * karcie, obie liczby byłyby poprawne i sprzeczne naraz.
 */
export const STRONG_MATCH_SCORE = 75;

/** Ranking C2 wyliczony z cache'u zapytania `["ai-matches", jobId, ""]`. */
export interface JobRankingSummary {
  /** Ilu kandydatów jest w rankingu. */
  total: number;
  /** Ilu ma wynik ≥ {@link STRONG_MATCH_SCORE}. */
  strong: number;
}

/**
 * Podsumowanie rankingu z odpowiedzi `GET /api/jobs/{id}/ai-matches`.
 *
 * `match_score` bywa `null` (kandydat bez policzonego wyniku) — taki wiersz
 * jest w rankingu, ale NIE jest mocnym trafieniem. Traktowanie go jak zera
 * dałoby ten sam wynik, ale z innego powodu; traktowanie jak trafienia
 * zawyżałoby liczbę, na którą patrzy się przy decyzji „w co wejść".
 */
export function summarizeRanking(
  matches: ReadonlyArray<{ match_score?: number | null }> | null | undefined,
): JobRankingSummary | null {
  if (!matches) return null;
  return {
    total: matches.length,
    strong: matches.filter(
      (m) => (m.match_score ?? -1) >= STRONG_MATCH_SCORE / 100,
    ).length,
  };
}

/** Kroki bez własnego pipeline'u — patrzą na wejście do procesu (ranking C2). */
const RANKING_TABS: ReadonlySet<JobDetailTab> = new Set<JobDetailTab>([
  "champion",
  "ai-matching",
  "manual-search",
  "portals",
  "history",
  "chat",
  "questions",
]);

export interface JobHeaderKpiInput {
  tab: JobDetailTab;
  /** `null` dopóki kanban się nie wczytał. */
  columns: KanbanColumn[] | null;
  /** `null`, gdy rankingu nie ma w cache'u (nie odpytujemy o niego sami). */
  ranking: JobRankingSummary | null;
}

/** Liczba dodatnia dostaje ton ostrzegawczy; zero zostaje neutralne. */
function toneWhenPositive(
  value: number | null,
  tone: JobHeaderKpiTone,
): JobHeaderKpiTone {
  return value != null && value > 0 ? tone : "neutral";
}

/**
 * Trzy KPI właściwe dla aktywnej zakładki.
 *
 * Zawsze DOKŁADNIE trzy pozycje — jobbar ma stałą szerokość klastra, a znikająca
 * kolumna liczb czytałaby się jak awaria, nie jak brak danych.
 */
export function buildJobHeaderKpis({
  tab,
  columns,
  ranking,
}: JobHeaderKpiInput): JobHeaderKpi[] {
  const inProcess = columns ? countInProcess(columns) : null;

  if (RANKING_TABS.has(tab)) {
    return [
      { key: "ranked", label: "w rankingu", value: ranking?.total ?? null, tone: "neutral" },
      {
        key: "strong",
        label: `≥ ${STRONG_MATCH_SCORE} pkt`,
        value: ranking?.strong ?? null,
        tone: ranking ? "ok" : "neutral",
      },
      { key: "in-process", label: "w procesie", value: inProcess, tone: "neutral" },
    ];
  }

  if (tab === "pipeline") {
    const stalled = columns ? countStalled(columns, 7) : null;
    return [
      { key: "in-process", label: "w procesie", value: inProcess, tone: "neutral" },
      {
        key: "stalled",
        label: "utknęli > 7 d",
        value: stalled,
        tone: toneWhenPositive(stalled, "warn"),
      },
      {
        key: "at-client",
        label: "u klienta",
        value: columns ? countExternal(columns) : null,
        tone: "neutral",
      },
    ];
  }

  if (tab === "screening") {
    const pending = columns ? selectPendingVerifications(columns).length : null;
    return [
      {
        key: "screening",
        label: "w screeningu",
        value: columns ? selectScreeningQueue(columns).length : null,
        tone: "neutral",
      },
      {
        key: "pending",
        label: "czeka na akceptację",
        value: pending,
        tone: toneWhenPositive(pending, "warn"),
      },
      {
        key: "verified",
        label: "zweryfikowani",
        value: columns ? selectVerifiedQueue(columns).length : null,
        tone: "neutral",
      },
    ];
  }

  if (tab === "cv") {
    return [
      {
        key: "to-send",
        label: "do wysłania",
        value: columns ? selectVerifiedQueue(columns).length : null,
        tone: "neutral",
      },
      {
        key: "cv-sent",
        label: "CV u klienta",
        value: columns ? countStage(columns, CV_SENT_STAGE) : null,
        tone: "neutral",
      },
      {
        key: "at-client",
        label: "u klienta",
        value: columns ? countExternal(columns) : null,
        tone: "neutral",
      },
    ];
  }

  if (tab === "interviews") {
    const veto = columns ? countHmVeto(columns) : null;
    const acceptance = columns ? countStage(columns, ACCEPTANCE_STAGE) : null;
    return [
      {
        key: "at-client",
        label: "u klienta",
        value: columns ? countExternal(columns) : null,
        tone: "neutral",
      },
      {
        key: "acceptance",
        label: "akceptacja",
        value: acceptance,
        tone: toneWhenPositive(acceptance, "ok"),
      },
      {
        key: "hm-veto",
        label: "weto HM",
        value: veto,
        tone: toneWhenPositive(veto, "bad"),
      },
    ];
  }

  // tab === "contract"
  const hired = columns ? countHired(columns) : null;
  return [
    {
      key: "contract-sent",
      label: "umowa wysłana",
      value: columns ? countContractSent(columns) : null,
      tone: "neutral",
    },
    {
      key: "hired",
      label: "zatrudnieni",
      value: hired,
      tone: toneWhenPositive(hired, "ok"),
    },
    {
      key: "contract-stages",
      label: "na etapach umowy",
      value: columns ? countContractStages(columns) : null,
      tone: "neutral",
    },
  ];
}
