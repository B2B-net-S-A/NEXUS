/**
 * P0 — rekrutacja ultrapilna przez 24 h (decyzje Artura 27.10.2026) — lustro
 * `backend/app/services/job_p0.py`.
 *
 * P0 to nakładka z terminem nad priorytetem: obowiązuje, dopóki rekrutacja
 * jest otwarta i nikt go nie zakończył — od 06.11.2026 także po terminie
 * (prośba Olafa: koniec potwierdza Head of Recruitment). Ustawia Head of Recruitment
 * albo administrator, z powodem, który widzą wszyscy. P0 stoi na górze listy
 * rekrutacji, Daily i w górnym pasku; na pulpicie każdej osoby jest stały
 * panel. Reguła: `docs/claude/rekrutacja-tablica/p0-ultrapilne-24-h.md`.
 */

export type P0Duration = "24h" | "48h" | "friday";

export const P0_DURATION_OPTIONS: ReadonlyArray<{ value: P0Duration; label: string }> = [
  { value: "24h", label: "24 h" },
  { value: "48h", label: "48 h" },
  { value: "friday", label: "do piątku" },
];

export const P0_REASON_MIN = 3;
export const P0_REASON_MAX = 300;

export const P0_LABEL = "P0 Teraz — ultrapilne";
// 28.10.2026 (propozycje Olafa): pulpit i górny pasek pokazują P0 tylko
// zespołowi rekrutacji; lista rekrutacji i Daily — wszystkim, jak dotąd.
export const P0_HINT =
  "Na górze listy rekrutacji i Daily, a w górnym pasku i na pulpicie u rekruterów i Delivery Leada tej rekrutacji. Po terminie trwa, dopóki Head of Recruitment go nie przedłuży albo nie zakończy; priorytet zostaje.";
export const P0_SET_BY_HINT =
  "P0 ustawia Head of Recruitment albo administrator; Delivery Lead rekrutacji może o nie poprosić.";
export const P0_REQUEST_HINT =
  "Head of Recruitment dostanie dzwonek i mail. P0 zacznie obowiązywać po zatwierdzeniu.";

/** Pola P0 rekrutacji albo requestu (`GET /api/jobs`, `/api/request-board`). */
export interface P0Source {
  is_p0?: boolean | null;
  p0_until?: string | null;
  p0_reason?: string | null;
  p0_set_by_name?: string | null;
  status?: string | null;
}

/**
 * Czy P0 obowiązuje. Od 06.11.2026 termin go nie kończy (koniec potwierdza
 * Head of Recruitment), więc decyduje serwer: oddaje `p0_until` tylko
 * rekrutacjom z P0 — przed terminem albo po nim, do decyzji.
 */
export function isP0Active(source: P0Source | null | undefined): boolean {
  if (!source || source.is_p0 === false || !source.p0_until) return false;
  if (source.status && source.status !== "published") return false;
  return Number.isFinite(Date.parse(source.p0_until));
}

/** Termin minął, P0 czeka na „Przedłuż o 24 h” albo „Zakończ P0”. */
export function isP0Overdue(source: P0Source | null | undefined, now: Date = new Date()): boolean {
  return isP0Active(source) && Date.parse(source?.p0_until ?? "") <= now.getTime();
}

/** Ile po terminie: „minęło 55 min”, „minęło 3 h”, „minęło 2 dni”. */
export function p0OverdueLabel(until: string, now: Date = new Date()): string {
  const minutes = Math.max(Math.floor((now.getTime() - Date.parse(until)) / 60_000), 0);
  if (minutes < 60) return `minęło ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `minęło ${hours} h`;
  return `minęło ${Math.floor(hours / 24)} dni`;
}

/** Ile zostało: „23 h”, „45 min”, „2 dni 4 h”. Po terminie — `null`. */
export function p0Remaining(until: string | null | undefined, now: Date = new Date()): string | null {
  if (!until) return null;
  const ms = Date.parse(until) - now.getTime();
  if (!Number.isFinite(ms) || ms <= 0) return null;
  const minutes = Math.ceil(ms / 60_000);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h`;
  const days = Math.floor(hours / 24);
  const rest = hours % 24;
  return rest ? `${days} dni ${rest} h` : `${days} dni`;
}

/** Koniec P0 po polsku, czas warszawski: „jutro 10:09”, „pt 30.10, 18:00”. */
export function p0UntilLabel(until: string, now: Date = new Date()): string {
  const date = new Date(until);
  const zone = "Europe/Warsaw";
  const day = (d: Date) => d.toLocaleDateString("pl-PL", { timeZone: zone });
  const time = date.toLocaleTimeString("pl-PL", { timeZone: zone, hour: "2-digit", minute: "2-digit" });
  if (day(date) === day(now)) return `dziś ${time}`;
  if (day(date) === day(new Date(now.getTime() + 86_400_000))) return `jutro ${time}`;
  const weekday = date.toLocaleDateString("pl-PL", { timeZone: zone, weekday: "short" });
  const dm = date.toLocaleDateString("pl-PL", { timeZone: zone, day: "2-digit", month: "2-digit" });
  return `${weekday} ${dm}, ${time}`;
}

/** Powód po przycięciu albo komunikat, czego brakuje. */
export function validateP0Reason(raw: string): { reason: string; error: string | null } {
  const reason = raw.replace(/\s+/g, " ").trim();
  if (reason.length < P0_REASON_MIN) {
    return { reason, error: "Napisz, po co P0 — zobaczą to wszyscy." };
  }
  if (reason.length > P0_REASON_MAX) {
    return { reason, error: `Powód może mieć najwyżej ${P0_REASON_MAX} znaków.` };
  }
  return { reason, error: null };
}
