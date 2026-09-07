/**
 * Grupowanie surowych etapów pipeline'u (`CandidateStage.stage`, patrz
 * `STAGE_LABEL` w `app/dashboard/delivery-lead/_components/tabs/ActiveJobsTab.tsx`)
 * w sześć grup mini-lejka listy rekrutacji (makieta „01 Lista”, krok C2-flow #4):
 * nowi · screening · zweryfikowani · u klienta · umowa · zatrudnieni.
 *
 * Osobny moduł, a nie funkcja lokalna w `JobsListV2` — test wiąże się z TĄ SAMĄ
 * funkcją, której używa komponent (wzorzec `jobs-url-filters.ts`).
 *
 * Dane wejściowe: `GET /api/jobs?include_stage_counts=true` — każdy wiersz
 * dostaje `stage_breakdown: {<stage>: count}` jednym dodatkowym GROUP BY na
 * całą stronę wyników (`backend/app/api/jobs.py::list_jobs`), zero zapytań
 * per wiersz.
 */

export type FunnelGroupKey =
  | "new"
  | "screening"
  | "verified"
  | "with_client"
  | "contract"
  | "hired";

export interface FunnelGroup {
  key: FunnelGroupKey;
  label: string;
  count: number;
}

export const FUNNEL_GROUP_ORDER: readonly FunnelGroupKey[] = [
  "new",
  "screening",
  "verified",
  "with_client",
  "contract",
  "hired",
];

export const FUNNEL_GROUP_LABELS: Record<FunnelGroupKey, string> = {
  new: "Nowi",
  screening: "Screening",
  verified: "Zweryfikowani",
  with_client: "U klienta",
  contract: "Umowa",
  hired: "Zatrudnieni",
};

// `prep_call` to rozmowa PRZED formalnym screeningiem — liczymy ją do "nowi",
// nie do "screening" (screening = etap `screening` wprost). `rejected` i
// `withdrawn` to stany terminalne odejścia z procesu — świadomie POZA sześcioma
// grupami (mini-lejek pokazuje postęp, nie odpady); ich sumę liczy
// `funnelRejectedTotal` osobno, dla dociekliwych.
const STAGE_TO_GROUP: Record<string, FunnelGroupKey> = {
  new: "new",
  prep_call: "new",
  screening: "screening",
  verified: "verified",
  cv_sent: "with_client",
  interview: "with_client",
  client_interview: "with_client",
  acceptance: "contract",
  negotiation: "contract",
  onboarding: "contract",
  hired: "hired",
};

const TERMINAL_NEGATIVE_STAGES: readonly string[] = ["rejected", "withdrawn"];

/**
 * `stage_breakdown` surowy z API → sześć grup w stałej kolejności (zawsze
 * wszystkie sześć kluczy, licznik 0 gdy brak kandydatów na danym etapie —
 * stały kształt ułatwia renderowanie paska bez warunków na brakujące klucze).
 *
 * Nieznany klucz etapu (przyszła wartość enuma, której ta mapa jeszcze nie zna)
 * jest po cichu pomijany z sumy — CELOWO: literówka w mapowaniu ma dać zaniżony
 * pasek, którego brak da się zauważyć na oko, a nie wyjątek wywalający całą listę.
 */
export function buildStageFunnel(
  stageBreakdown: Record<string, number> | null | undefined,
): FunnelGroup[] {
  const totals: Record<FunnelGroupKey, number> = {
    new: 0,
    screening: 0,
    verified: 0,
    with_client: 0,
    contract: 0,
    hired: 0,
  };
  if (stageBreakdown) {
    for (const [stage, count] of Object.entries(stageBreakdown)) {
      const group = STAGE_TO_GROUP[stage];
      if (group && typeof count === "number") {
        totals[group] += count;
      }
    }
  }
  return FUNNEL_GROUP_ORDER.map((key) => ({
    key,
    label: FUNNEL_GROUP_LABELS[key],
    count: totals[key],
  }));
}

/** Suma sześciu grup — "ile kandydatów jest gdziekolwiek w tej rekrutacji". */
export function funnelTotal(groups: readonly FunnelGroup[]): number {
  return groups.reduce((sum, g) => sum + g.count, 0);
}

/** Odrzuceni + wycofani — poza sześcioma grupami, liczeni osobno. */
export function funnelRejectedTotal(
  stageBreakdown: Record<string, number> | null | undefined,
): number {
  if (!stageBreakdown) return 0;
  return TERMINAL_NEGATIVE_STAGES.reduce(
    (sum, stage) => sum + (stageBreakdown[stage] ?? 0),
    0,
  );
}

/** Krótki opis do `title` (tooltip) paska — pomija grupy zerowe. */
export function funnelTooltip(groups: readonly FunnelGroup[]): string {
  const nonZero = groups.filter((g) => g.count > 0);
  if (nonZero.length === 0) return "Brak kandydatów w tej rekrutacji.";
  return nonZero.map((g) => `${g.label}: ${g.count}`).join(" · ");
}
