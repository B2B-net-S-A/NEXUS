// Czyste pomocniki listy „Opieka · Ten tydzień” (bez Reacta — testowalne bez montowania).

import {
  FRONT_OFFICE_REASON_LABELS,
  type FrontOfficeReason,
  type WeekContact,
  type WeekReason,
} from "@/lib/api/care";
import { formatDayMonthPl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";

const ISO = /^(\d{4})-(\d{2})-(\d{2})$/;

/** Data `days` dni po `iso` (RRRR-MM-DD), bez przesunięć strefy. */
export function shiftIso(iso: string, days: number): string {
  const match = ISO.exec(iso);
  if (!match) return iso;
  const moment = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]) + days));
  return moment.toISOString().slice(0, 10);
}

/** „19–23.10” albo „28.10–01.11” — tydzień pracy w nagłówku listy. */
export function weekRangeLabel(from: string, to: string): string {
  const a = ISO.exec(from);
  const b = ISO.exec(to);
  if (!a || !b) return `${from} – ${to}`;
  if (a[2] === b[2]) return `${a[3]}–${b[3]}.${b[2]}`;
  return `${a[3]}.${a[2]}–${b[3]}.${b[2]}`;
}

/** Powód kontaktu w jednej linii: „zaległa 3 dni · dzień 30”, „umówiony 01.10”. */
export function reasonText(reason: WeekReason, today: string): string {
  const what =
    reason.kind === "follow_up"
      ? `umówiony kontakt${reason.from_conversation_on ? ` z ${formatDayMonthPl(reason.from_conversation_on)}` : ""}`
      : reason.kind === "pre_end"
        ? "30 dni przed końcem zamówienia"
        : reason.label.toLowerCase();
  if (reason.due_on < today) {
    const days = daysBetween(reason.due_on, today);
    return `zaległy ${countPl(days, "dzień", "dni", "dni")} · ${what}`;
  }
  if (reason.due_on === today) return `dziś · ${what}`;
  return `${formatDayMonthPl(reason.due_on)} · ${what}`;
}

/** Dni między dwiema datami RRRR-MM-DD (b − a). */
export function daysBetween(a: string, b: string): number {
  const ma = ISO.exec(a);
  const mb = ISO.exec(b);
  if (!ma || !mb) return 0;
  const ta = Date.UTC(Number(ma[1]), Number(ma[2]) - 1, Number(ma[3]));
  const tb = Date.UTC(Number(mb[1]), Number(mb[2]) - 1, Number(mb[3]));
  return Math.round((tb - ta) / 86_400_000);
}

const SIGNAL_LABELS: Record<string, string> = {
  attrition_risk: "ryzyko odejścia",
  wants_change: "chce zmiany projektu",
  project_end: "koniec projektu",
  client_hiring: "klient zatrudnia",
};

/** „Ostatnio” przy rozmowie: sygnały z kolejki przepięć, potem fragment notatki. */
export function lastContactText(row: WeekContact): string | null {
  const signals = row.signals.map((s) => SIGNAL_LABELS[s] ?? s);
  if (signals.length) return `sygnał: ${signals.join(", ")}`;
  const last = row.last_conversation;
  if (!last) return null;
  if (last.note_excerpt) return last.note_excerpt;
  const lastSignals = last.signals.map((s) => SIGNAL_LABELS[s] ?? s);
  return lastSignals.length ? lastSignals.join(", ") : null;
}

/** „kończy projekt · chce zmiany projektu”. */
export function frontOfficeText(reasons: FrontOfficeReason[]): string {
  return reasons.map((r) => FRONT_OFFICE_REASON_LABELS[r]).join(" · ");
}

/** Konsultanci menedżera w prośbie o opinię: „Jan K., Ewa L.” (imię + inicjał). */
export function shortNames(names: (string | null)[]): string {
  return names
    .map((name) => {
      const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
      if (!parts.length) return "konsultant";
      if (parts.length === 1) return parts[0];
      return `${parts[0]} ${parts[parts.length - 1][0]}.`;
    })
    .join(", ");
}
