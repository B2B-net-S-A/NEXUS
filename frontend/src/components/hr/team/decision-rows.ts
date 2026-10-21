// „Do Twojej decyzji” jako zwarte wiersze (przebudowa „Ludzi”, 22.10.2026):
// znacznik rodzaju, imię, krótkie podsumowanie i wiek sprawy. Karty liczy
// `decisionCards` (te same sprawy co dotąd), tu tylko słowa wiersza.
//
// Słowa neutralne wobec PIP (ekran wielu osób): „nieobecność”, „raport
// godzin”, „wynagrodzenie dodatkowe”. Wiersz premii bez kwoty — kwoty są
// w kolumnie „Premie w drodze”, którą serwer wypełnia tylko przy `sees_bonuses` (D2).

import { daysLabel, formatRange } from "@/components/hr/leave/leave-format";
import type { MyTeam } from "@/lib/api/hr-team";
import { monthYearPl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";

import { daysSince, decisionCards, type DecisionCard } from "./team-week";

/** Ile wierszy widać w „Moim zespole”; reszta jest w „Akceptacjach”. */
export const VISIBLE_DECISIONS = 3;

export const DECISION_TAGS: Record<DecisionCard["kind"], string> = {
  leave: "nieobecność",
  timesheet: "raport godzin",
  bonus: "do wiadomości",
};

export interface DecisionRow {
  key: string;
  card: DecisionCard;
  tag: string;
  name: string;
  summary: string;
  /** „czeka 5 dni”; brak — starszy serwer nie wysłał daty. */
  age?: string;
}

/** „czeka od dziś” / „czeka 1 dzień” / „czeka 5 dni”. */
export function waitingLabel(instant: string | null | undefined, today: string): string | undefined {
  const days = daysSince(instant, today);
  if (days === null) return undefined;
  if (days === 0) return "czeka od dziś";
  return `czeka ${days === 1 ? "1 dzień" : `${days} dni`}`;
}

function rowOf(card: DecisionCard, today: string): DecisionRow {
  const base = { key: card.key, card, tag: DECISION_TAGS[card.kind], name: card.person.name };
  if (card.kind === "leave") {
    return {
      ...base,
      summary: `${formatRange(card.item.start_date, card.item.end_date)} · ${daysLabel(card.item.days_total)}`,
      age: waitingLabel(card.item.created_at, today),
    };
  }
  if (card.kind === "timesheet") {
    return {
      ...base,
      summary: [monthYearPl(card.item), card.hoursText].filter(Boolean).join(" · "),
      age: waitingLabel(card.item.submitted_at, today),
    };
  }
  const proposals = card.person.bonuses?.proposals ?? 0;
  return {
    ...base,
    summary: `wynagrodzenie dodatkowe · ${countPl(
      proposals,
      "propozycja",
      "propozycje",
      "propozycji",
    )} — decydują Płace`,
  };
}

/** Wiersze w kolejności kart: wnioski, raporty godzin, potem premie do wiadomości. */
export function decisionRows(team: MyTeam): DecisionRow[] {
  return decisionCards(team).map((card) => rowOf(card, team.today));
}
