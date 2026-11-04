// Odpowiedź kandydata na zaproszenie na prep (0453, 17.10.2026, D5).
// Serwer czyta ją z Outlooka prowadzącego co 10 minut; tu tylko zdanie
// i kolor do plakietki przy prepie (dok osoby, panel kalendarza).

import type { Prep } from "@/lib/api/prepMeetings";
import { formatDayLabel, formatTime } from "@/lib/interview-cycle";

export type PrepResponseTone = "ok" | "info" | "wait" | "muted";

export interface PrepResponseView {
  label: string;
  tone: PrepResponseTone;
  /** Termin zaproponowany przez kandydata — do „Przyjmij termin”. */
  proposed: { start: string; end: string } | null;
}

const DAY_MS = 24 * 60 * 60_000;

/**
 * Czyste: plakietka odpowiedzi kandydata. `null` = nic do pokazania
 * (prep odwołany albo odpowiedzi jeszcze nie sprawdzano — prep sprzed 0453).
 * „Czeka na odpowiedź” nie znaczy „nie przyjdzie”: część kandydatów przyjmuje
 * w Gmailu bez wysłania odpowiedzi.
 */
export function prepResponseView(
  prep: Pick<Prep, "candidate_response" | "proposed_start" | "proposed_end" | "start" | "status">,
  now: Date = new Date(),
): PrepResponseView | null {
  if (prep.status === "cancelled" || prep.candidate_response == null) return null;
  if (prep.proposed_start && prep.proposed_end) {
    return {
      label: `Kandydat proponuje: ${formatDayLabel(prep.proposed_start, now)} · ${formatTime(prep.proposed_start)}`,
      tone: "wait",
      proposed: { start: prep.proposed_start, end: prep.proposed_end },
    };
  }
  switch (prep.candidate_response) {
    case "accepted":
      return { label: "Kandydat przyjął", tone: "ok", proposed: null };
    case "tentative":
      return { label: "Kandydat: może", tone: "info", proposed: null };
    case "declined":
      return { label: "Kandydat odrzucił", tone: "wait", proposed: null };
    default: {
      const left = new Date(prep.start).getTime() - now.getTime();
      return left > 0 && left <= DAY_MS
        ? { label: "Brak odpowiedzi kandydata", tone: "wait", proposed: null }
        : { label: "Czeka na odpowiedź kandydata", tone: "muted", proposed: null };
    }
  }
}
