// Czyste reguły zakładek portalu w back office (testy bez przeglądarki i bez API).

export const TRANSCRIPT_LABELS: Record<string, string> = {
  waiting: "Transkryptu jeszcze nie ma. Pobierzemy go po rozmowie.",
  missing: "Transkrypt nie powstał.",
  forbidden: "Brak dostępu do transkryptu: sprawdź konfigurację konta organizatora.",
  error: "Nie udało się pobrać transkryptu. Spróbujemy ponownie.",
  cancelled: "Rozmowa odwołana.",
};

const WHEN = new Intl.DateTimeFormat("pl-PL", {
  timeZone: "Europe/Warsaw",
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatWhen(iso: string): string {
  return WHEN.format(new Date(iso));
}

/** „4,3 / 5”; brak ocen to kreska, a nie zero. */
export function averageLabel(value: number | null): string {
  return value == null ? "—" : `${value.toFixed(1).replace(".", ",")} / 5`;
}

export function percentLabel(value: number | null): string {
  return value == null ? "—" : `${value}%`;
}

export function answeredShare(rated: number, meetings: number): string {
  return meetings > 0 ? `${Math.round((100 * rated) / meetings)}%` : "—";
}

export function takeLabel(minutes: number | null): string {
  if (minutes == null) return "—";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

export const PORTAL_STATE_LABELS = {
  off: "Portal wyłączony: konsultanci go nie widzą, a maile nie wychodzą.",
  pilot: "Portal w pilotażu: działa dla wybranych kontraktów.",
  all: "Portal włączony dla wszystkich konsultantów.",
} as const;
