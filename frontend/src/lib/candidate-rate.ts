// „Stawka od” (0414, decyzje Artura 04.10.2026) — czyste reguły opisu.
//
// Liczy SERWER (najniższa stawka z 18 miesięcy, jawne minimum, „Nie licz
// jako minimum”). Tu wyłącznie to, jak tę liczbę pokazać: w profilu, na
// liście, w propozycjach i w oknie historii.

import { countPl } from "@/lib/plural-pl";

const MONTH_YEAR = new Intl.DateTimeFormat("pl-PL", {
  month: "2-digit",
  year: "numeric",
  timeZone: "Europe/Warsaw",
});

const DAY = new Intl.DateTimeFormat("pl-PL", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  timeZone: "Europe/Warsaw",
});

export function toAmount(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function parse(value: string | null | undefined): Date | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** „80 zł/h”, „125,19 zł/h”. */
export function hourlyText(value: unknown): string | null {
  const n = toAmount(value);
  if (n === null) return null;
  const text = n.toLocaleString("pl-PL", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
  return `${text} zł/h`;
}

/** „08.2025”. */
export function monthYear(value: string | null | undefined): string | null {
  const d = parse(value);
  return d ? MONTH_YEAR.format(d) : null;
}

export function dayText(value: string | null | undefined): string | null {
  const d = parse(value);
  return d ? DAY.format(d) : null;
}

export interface RateFromFields {
  rate_from_hourly?: string | number | null;
  rate_from_at?: string | null;
  rate_from_stale?: boolean | null;
  rate_latest_hourly?: string | number | null;
  rate_latest_at?: string | null;
  rate_observation_count?: number | null;
}

/** „od 80 zł/h”; stara stawka spoza 18 miesięcy z dopiskiem roku. */
export function rateFromText(fields: RateFromFields): string | null {
  const text = hourlyText(fields.rate_from_hourly);
  if (!text) return null;
  if (fields.rate_from_stale) {
    const year = parse(fields.rate_from_at ?? null)?.getFullYear();
    return year ? `od ${text} · z ${year}` : `od ${text} · nieaktualna`;
  }
  return `od ${text}`;
}

/**
 * Druga linia: „ostatnio 140 zł/h (06.2026) · 7 stawek”. Tylko gdy ostatnio
 * podana różni się od najniższej — inaczej nie mówi nic nowego.
 */
export function rateSecondLine(fields: RateFromFields): string | null {
  const from = toAmount(fields.rate_from_hourly);
  const latest = toAmount(fields.rate_latest_hourly);
  if (from === null || latest === null || Math.abs(latest - from) < 0.005) {
    return null;
  }
  const parts = [`ostatnio ${hourlyText(latest)}`];
  const when = monthYear(fields.rate_latest_at ?? null);
  if (when) parts[0] += ` (${when})`;
  const count = fields.rate_observation_count ?? 0;
  if (count > 1) parts.push(countPl(count, "stawka", "stawki", "stawek"));
  return parts.join(" · ");
}

/** „W tej rekrutacji: 135 zł/h”, a bez stawki — kandydata o tę rolę nie pytano. */
export function thisJobRateText(value: unknown): string {
  const text = hourlyText(value);
  return text ? `W tej rekrutacji: ${text}` : "W tej rekrutacji: nie pytano";
}

/** „Stawka od 80 zł/h · DevOps / Admin, 08.2025”. */
export function rateFromContextLine(rateFrom: {
  amount: string | number;
  at: string | null;
  job_title: string | null;
  stale?: boolean;
} | null): string | null {
  if (!rateFrom) return null;
  const text = hourlyText(rateFrom.amount);
  if (!text) return null;
  const when = monthYear(rateFrom.at);
  const where = [rateFrom.job_title, when].filter(Boolean).join(", ");
  const stale = rateFrom.stale ? " (nieaktualna)" : "";
  return where ? `Stawka od ${text}${stale} · ${where}` : `Stawka od ${text}${stale}`;
}

const SOURCE_LABEL: Record<string, string> = {
  card: "Karta rekomendacji",
  card_manual: "Karta rekomendacji (wpisane ręcznie)",
  stage: "Okno „Zweryfikowany”",
  application: "Formularz zgłoszenia",
  profile: "Profil",
  profile_manual: "Profil, wpisane ręcznie",
  profile_manual_minimum: "Profil — minimum ustawione ręcznie",
  profile_stage_minimum: "Minimum z okna „Zweryfikowany”",
  profile_trainee_call: "Telefon praktykanta (minimum)",
  profile_notes_confirmed: "Z notatek, zatwierdzone",
  profile_notes_ai: "Z notatek (AI)",
  profile_notes_removed: "Z notatek (usunięte)",
  profile_candidate_merge: "Scalenie duplikatów",
  // 0418: zmiana stawki w trakcie procesu.
  rate_requested: "Zgłoszona zmiana stawki",
  rate_agreed: "Ustalona po negocjacji",
};

export function rateSourceLabel(source: string | null | undefined): string {
  if (!source) return "Nieznane źródło";
  return SOURCE_LABEL[source] ?? (source.startsWith("profile_") ? "Profil" : source);
}

export function rateReasonLabel(
  reason: string,
  excludedByName?: string | null,
): string {
  switch (reason) {
    case "minimum":
      return "liczy się jako minimum";
    case "counts":
      return "liczy się";
    case "excluded":
      return excludedByName
        ? `wyłączona przez: ${excludedByName}`
        : "wyłączona z minimum";
    case "outside_window":
      return "starsza niż 18 miesięcy";
    case "superseded":
      return "niższa niż późniejsze minimum";
    default:
      return "inna waluta lub jednostka";
  }
}
