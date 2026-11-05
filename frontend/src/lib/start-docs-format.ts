// Teksty „Dokumentów do startu”: jedna reguła dla karty, pulpitu i paska.

import type { StartDocTone } from "@/lib/api/start-documents";

/** Data ISO jako DD.MM (bez strefy: to dzień z kalendarza firmy). */
export function dayMonth(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const [, month, day] = iso.slice(0, 10).split("-");
  return month && day ? `${day}.${month}` : null;
}

export function deadlineText(deadline: string | null, tone: StartDocTone): string | null {
  const day = dayMonth(deadline);
  if (!day) return null;
  if (tone === "late") return `po terminie od ${day}`;
  if (tone === "today") return "termin dziś";
  return `termin ${day}`;
}

/** „Start 09.11, termin dziś” albo „Start jeszcze nieustalony”. */
export function startLine(
  start: string | null,
  deadline: string | null,
  tone: StartDocTone,
): string {
  const day = dayMonth(start);
  if (!day) return "Start jeszcze nieustalony";
  const when = deadlineText(deadline, tone);
  return when ? `Start ${day}, ${when}` : `Start ${day}`;
}

export function offsetText(offset: number): string {
  if (offset === 0) return "W dniu startu";
  const days = Math.abs(offset);
  const unit = days === 1 ? "dzień roboczy" : "dni robocze";
  return offset < 0 ? `${days} ${unit} przed startem` : `${days} ${unit} po starcie`;
}
