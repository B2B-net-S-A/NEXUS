// Zdanie „Kafelek liczy…" w kreatorze metryki — ta sama definicja, którą
// serwer policzy, opisana po polsku, żeby dało się ją sprawdzić wzrokiem
// przed dodaniem kafelka.

import type { MetricDefinition } from "@/lib/api/userDashboard";
import { PERIOD_LABELS } from "@/lib/dashboard-tiles/layout";

const STAGE_LABELS: Record<string, string> = {
  verified: "Zweryfikowani",
  cv_sent: "CV wysłane",
  interview: "Rozmowa",
  client_interview: "Rozmowa z klientem",
  acceptance: "Akceptacja",
  hired: "Zatrudnieni",
};

const MEASURE_SENTENCES: Record<string, string> = {
  "candidates.new": "liczbę nowych kandydatów w bazie",
  "jobs.opened": "liczbę otwartych rekrutacji",
  "jobs.closed": "liczbę zamkniętych rekrutacji",
  "jobs.open_now": "liczbę rekrutacji otwartych teraz",
  "contracts.active_now": "liczbę kontraktów obowiązujących dziś",
  "contracts.started": "liczbę rozpoczętych kontraktów",
  "contracts.ended": "liczbę zakończonych kontraktów",
  "orders.ending_30_days": "zamówienia kończące się w ciągu 30 dni",
  "orders.started": "liczbę rozpoczętych zamówień",
  "finance.revenue": "miesięczny przychód z kontraktów",
  "finance.margin": "miesięczną marżę z kontraktów",
  "finance.cost": "miesięczny koszt konsultantów",
};

const GROUP_SENTENCES: Record<string, string> = {
  week: "tydzień po tygodniu",
  month: "miesiąc po miesiącu",
  client: "w podziale na klientów",
  recruiter: "w podziale na osoby",
  stage: "w podziale na etapy",
  competence_category: "w podziale na kategorie kompetencji",
};

const AUTHOR_SENTENCES = {
  me: "Twoje",
  team: "Twojego zespołu",
  all: "całej firmy",
} as const;

const SNAPSHOT = new Set(["open_now", "active_now", "ending_30_days"]);
const WITH_AUTHOR = new Set(["pipeline_moves", "candidates", "jobs"]);

export function describeMetric(
  metric: MetricDefinition,
  names: { clients?: string[]; categories?: string[] } = {},
): string {
  const parts: string[] = [];
  if (metric.source === "pipeline_moves") {
    parts.push(
      metric.group_by === "stage"
        ? "Liczbę osób, które po raz pierwszy doszły do każdego etapu"
        : `Liczbę osób, które po raz pierwszy doszły do etapu „${
            STAGE_LABELS[metric.stage ?? ""] ?? metric.stage
          }”`,
    );
  } else {
    const sentence = MEASURE_SENTENCES[`${metric.source}.${metric.measure}`];
    parts.push(sentence ? sentence.charAt(0).toUpperCase() + sentence.slice(1) : "Metrykę");
  }
  if (WITH_AUTHOR.has(metric.source)) {
    parts.push(`— dane ${AUTHOR_SENTENCES[metric.filters?.author ?? "me"]}`);
  }
  if (names.clients?.length) {
    parts.push(`u klienta ${names.clients.join(", ")}`);
  }
  if (names.categories?.length) {
    parts.push(`w kategorii ${names.categories.join(", ")}`);
  }
  const group = metric.group_by && metric.group_by !== "none" ? GROUP_SENTENCES[metric.group_by] : null;
  if (group && group !== GROUP_SENTENCES.stage) parts[parts.length - 1] += `, ${group}`;
  if (SNAPSHOT.has(metric.measure)) {
    parts.push("— stan na dziś");
  } else if (metric.source === "finance" && metric.group_by !== "month") {
    parts.push("— stan na dziś");
  } else {
    parts.push(`— okres: ${PERIOD_LABELS[metric.period ?? "last_30_days"]}`);
  }
  if (metric.compare_previous && !SNAPSHOT.has(metric.measure) && metric.source !== "finance") {
    parts.push("(ze zmianą względem poprzedniego okresu)");
  }
  const sentence = `${parts.join(" ")}.`;
  // Lustro serwera (custom_metrics/engine.py): gdy ruchy są przypisywane
  // ludziom, zasługa idzie jak w „Moje KPI”, nie do osoby, która kliknęła etap.
  if (metric.source === "pipeline_moves" && creditsPeople(metric)) {
    return `${sentence} ${CREDIT_SENTENCE}`;
  }
  return sentence;
}

export const CREDIT_SENTENCE =
  "Zasługa jak w „Moje KPI”: ruch liczy się osobie, która zweryfikowała kandydata.";

function creditsPeople(metric: MetricDefinition): boolean {
  const author = metric.filters?.author ?? "me";
  return author !== "all" || metric.group_by === "recruiter";
}
