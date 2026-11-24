// Terminy przetargów w kalendarzu firmy (Europe/Warsaw), bez zależności od strefy przeglądarki.

const ZONE = "Europe/Warsaw";

/** Dzisiejsza data firmy jako `YYYY-MM-DD`. */
export function businessToday(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: ZONE }).format(now);
}

function dayNumber(isoDate: string): number {
  const [year, month, day] = isoDate.split("-").map(Number);
  return Date.UTC(year, month - 1, day) / 86_400_000;
}

export interface DeadlineLabel {
  date: string;
  hint: string;
  /** Termin minął albo wypada dziś. */
  urgent: boolean;
  past: boolean;
}

/** „25.11, 10:00” i „za 5 dni” / „dziś” / „po terminie”. */
export function deadlineLabel(
  deadlineDate: string | null,
  deadlineAt: string | null,
  today: string,
): DeadlineLabel | null {
  if (!deadlineDate) return null;
  const [, month, day] = deadlineDate.split("-");
  const time = deadlineAt
    ? new Date(deadlineAt).toLocaleTimeString("pl-PL", { timeZone: ZONE, hour: "2-digit", minute: "2-digit" })
    : null;
  const days = dayNumber(deadlineDate) - dayNumber(today);
  const pastByTime = deadlineAt !== null && new Date(deadlineAt).getTime() <= Date.now();
  const past = days < 0 || pastByTime;
  let hint: string;
  if (past) hint = "po terminie";
  else if (days === 0) hint = "dziś";
  else if (days === 1) hint = "jutro";
  else hint = `za ${days} dni`;
  return { date: `${day}.${month}${time ? `, ${time}` : ""}`, hint, urgent: past || days <= 1, past };
}

/** „24.11, 05:31” dla chwili z API. */
export function formatMoment(iso: string): string {
  return new Date(iso).toLocaleString("pl-PL", {
    timeZone: ZONE,
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
