// Czyste funkcje panelu „Moi ludzie": grupowanie, etykiety, zdania awatara.
//
// Zdania są z SZABLONÓW, nie z modelu (decyzja 21.09.2026: zero AI, zero
// kosztu, zero zmyślania). Awatar mówi wyłącznie wtedy, gdy ma konkret —
// pusta lista zdań znaczy „milcz", nie „pokaż ogólnik".

import type { MyPeopleRow, MyPeopleSummary } from "@/lib/api/myPeople";

export const UNCATEGORIZED_LABEL = "Pozostałe";

/** Etapy, które mogą być „najdalszym" — lista zawiera tylko ludzi po wysyłce. */
export const FURTHEST_STAGE_LABELS: Record<string, string> = {
  verified: "Zweryfikowany",
  interview: "Rozmowa",
  cv_sent: "CV wysłane",
  client_interview: "Rozmowa u klienta",
  acceptance: "Akceptacja",
  negotiation: "Negocjacje",
  onboarding: "Onboarding",
  hired: "Zatrudniony",
};

export function furthestStageLabel(stage: string | null): string | null {
  if (!stage) return null;
  return FURTHEST_STAGE_LABELS[stage] ?? null;
}

/** Polska forma liczebnika: (1, „osoba", „osoby", „osób"). */
export function plural(n: number, one: string, few: string, many: string): string {
  if (n === 1) return one;
  const mod10 = n % 10;
  const mod100 = n % 100;
  return mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14) ? few : many;
}

export function daysAgoLabel(days: number | null): string | null {
  if (days == null) return null;
  if (days === 0) return "dziś";
  if (days === 1) return "wczoraj";
  return `${days} ${plural(days, "dzień", "dni", "dni")} temu`;
}

export interface PeopleGroup {
  key: string;
  categoryId: number | null;
  label: string;
  rows: MyPeopleRow[];
}

/**
 * Aktywni pogrupowani po kategorii kompetencji. Kolejność grup = kolejność
 * katalogu kategorii, „Pozostałe" na końcu. Kolejność w grupie przychodzi
 * z serwera (najdalszy etap, potem najświeższa wysyłka) i nie jest zmieniana.
 */
export function groupByCategory(
  rows: MyPeopleRow[],
  categories: { id: number; name_pl: string }[],
): PeopleGroup[] {
  const known = new Map(categories.map((c) => [c.id, c.name_pl]));
  const buckets = new Map<number | null, MyPeopleRow[]>();
  for (const row of rows) {
    const key = row.category_id != null && known.has(row.category_id) ? row.category_id : null;
    const list = buckets.get(key) ?? [];
    list.push(row);
    buckets.set(key, list);
  }
  const groups: PeopleGroup[] = [];
  for (const cat of categories) {
    const list = buckets.get(cat.id);
    if (list?.length) {
      groups.push({ key: `cc-${cat.id}`, categoryId: cat.id, label: cat.name_pl, rows: list });
    }
  }
  const rest = buckets.get(null);
  if (rest?.length) {
    groups.push({ key: "cc-none", categoryId: null, label: UNCATEGORIZED_LABEL, rows: rest });
  }
  return groups;
}

export interface SplitPeople {
  active: MyPeopleRow[];
  working: MyPeopleRow[];
  snoozed: MyPeopleRow[];
}

export function splitPeople(rows: MyPeopleRow[]): SplitPeople {
  return {
    active: rows.filter((r) => !r.snoozed && !r.working),
    working: rows.filter((r) => !r.snoozed && r.working),
    snoozed: rows.filter((r) => r.snoozed),
  };
}

export function matchesQuery(row: MyPeopleRow, query: string): boolean {
  const q = query.trim().toLocaleLowerCase("pl");
  if (!q) return true;
  return [row.full_name, row.last_sent_client_name, row.last_sent_job_title, row.city]
    .filter(Boolean)
    .some((v) => (v as string).toLocaleLowerCase("pl").includes(q));
}

/**
 * Zdania dymka awatara i nagłówka panelu. Kolejność = pilność:
 * nowe dopasowania, potem ludzie czekający najdłużej bez wysyłki.
 */
export function summarySentences(summary: MyPeopleSummary | undefined | null): string[] {
  if (!summary) return [];
  const out: string[] = [];
  if (summary.new_matches > 0) {
    const jobs = summary.jobs_with_matches;
    const people = summary.new_matches;
    out.push(
      `${jobs} ${plural(jobs, "nowa rekrutacja pasuje", "nowe rekrutacje pasują", "nowych rekrutacji pasuje")} ` +
        `do ${people} ${plural(people, "osoby", "osób", "osób")} z Twojej listy.`,
    );
    const top = summary.latest_matches[0];
    if (top) {
      out.push(`Na przykład ${top.full_name} → „${top.job_title}”.`);
    }
  }
  if (summary.idle_count > 0) {
    const first = summary.idle_top[0];
    if (first) {
      out.push(
        `${first.full_name} czeka ${first.days_since_last_send} ${plural(first.days_since_last_send, "dzień", "dni", "dni")} bez wysyłki` +
          (summary.idle_count > 1
            ? ` — i jeszcze ${summary.idle_count - 1} ${plural(summary.idle_count - 1, "osoba", "osoby", "osób")}.`
            : "."),
      );
    }
  }
  return out;
}

/** Klucz treści dymka — dymek pokazuje się raz na sesję dla tej samej treści. */
export function sentencesKey(sentences: string[]): string {
  return sentences.join("|");
}

// ── Jarvis ──────────────────────────────────────────────────────────────────

/** Zdarzenie okna: przyszedł dzwonek `my_people_match` (z `useNotifications`). */
export const MY_PEOPLE_MATCH_EVENT = "nexus:my-people-match";

export interface MyPeopleMatchEventDetail {
  title: string;
  link?: string | null;
}

/** `/jobs/42?people=1` → 42. Link pochodzi z serwera, ale bywa pusty. */
export function jobIdFromMatchLink(link: string | null | undefined): number | null {
  const m = link?.match(/^\/jobs\/(\d+)/);
  return m ? Number(m[1]) : null;
}

/** Pytanie, które Jarvis wysyła po kliknięciu dymka o nowej rekrutacji. */
export function reassignPrompt(jobId: number | null): string {
  return jobId != null
    ? `Kogo z moich ludzi warto przepiąć na rekrutację #${jobId}? Pokaż najlepiej pasujących i przygotuj dodanie.`
    : "Kogo z moich ludzi warto teraz przepiąć na otwarte rekrutacje?";
}

/**
 * Fragmenty porannego skrótu Jarvisa („Na dziś: …"). Bez modelu, ta sama
 * reguła co zdania postaci „Moi ludzie" — tylko konkret, pusta lista = cisza.
 */
export function briefFragments(summary: MyPeopleSummary | undefined | null): string[] {
  if (!summary) return [];
  const out: string[] = [];
  if (summary.jobs_with_matches > 0) {
    const n = summary.jobs_with_matches;
    out.push(
      `${n} ${plural(n, "nowa rekrutacja pasuje", "nowe rekrutacje pasują", "nowych rekrutacji pasuje")} do Twoich ludzi`,
    );
  }
  if (summary.idle_count > 0) {
    const n = summary.idle_count;
    out.push(
      `${n} ${plural(n, "osoba czeka", "osoby czekają", "osób czeka")} ponad ${summary.idle_days} dni bez wysyłki`,
    );
  }
  return out;
}
