// „Twoje CV w drodze” — teksty listy rekrutera w panelu „Czeka na Ciebie”.
//
// Serwer (`services/cv_in_transit.py`) rozstrzyga, które CV są „moje” i do
// której grupy trafiają; tu są wyłącznie zdania, które widzi człowiek.

import type { CvInTransit, CvTransitKind, CvTransitRow } from "@/lib/api/boardTasks";
import { warsawToday } from "@/lib/warsaw-date";

export const CV_TRANSIT_TITLE = "Twoje CV w drodze";

export const CV_TRANSIT_HINT = "CV, które poszły od Ciebie dalej. Na górze te, które wróciły.";

export const CV_TRANSIT_EMPTY =
  "Nie masz teraz CV w drodze. Tu zobaczysz CV przekazane do QC i wysłane do klienta.";

/** Plakietka wiersza „Wróciło do Ciebie”. */
export const CV_TRANSIT_RETURNED_LABEL: Record<
  Extract<CvTransitKind, "rejected_by_dl" | "sent_back" | "cpro_returned">,
  string
> = {
  rejected_by_dl: "Odrzucone przez DL",
  sent_back: "Cofnięte do poprawy",
  cpro_returned: "Zwrot z kolejki Cpro",
};

export function transitIsEmpty(transit: CvInTransit): boolean {
  return transit.returned_total + transit.in_review_total + transit.sent_total === 0;
}

/** Jedna linia pod listą zwróconych: ile CV jest jeszcze w drodze. */
export function transitSummary(transit: CvInTransit): string {
  return `W przeglądzie: ${transit.in_review_total} · Wysłane do klienta: ${transit.sent_total}`;
}

export function transitJobLabel(row: CvTransitRow): string {
  const title = row.job_working_title?.trim() || row.job_title;
  return row.client_name ? `${title} · ${row.client_name}` : title;
}

/** Trzecia linia wiersza: u kogo karta czeka albo kto ją wysłał. Osobna
 *  linia, bo w wąskiej kolumnie panelu doklejona do rekrutacji była ucinana. */
export function transitRowWho(row: CvTransitRow): string | null {
  if (row.kind === "in_review") {
    return `Przegląda: ${row.holder_name ?? "Delivery Lead klienta"}`;
  }
  if (row.kind === "cpro_queue") {
    return row.holder_name ? `Kolejka Cpro: ${row.holder_name}` : "Kolejka Cpro";
  }
  if (row.kind === "sent") {
    return row.actor_name ? `Wysłane przez: ${row.actor_name}` : null;
  }
  return null;
}

/** Tekst obok plakietki „wróciło”: powód, a gdy go nie ma — kto to zrobił. */
export function transitReturnedDetail(row: CvTransitRow): string | null {
  const reason = row.reason?.trim();
  if (reason) return reason;
  return row.actor_name?.trim() || null;
}

/** Uwaga dla rekrutera zostawiona przy decyzji — osobna linia wiersza. */
/** D6 (08.10.2026): „Do poprawy (N): a, b, c” — pola wskazane przez DL. */
export function transitFixList(row: CvTransitRow): string | null {
  const labels = (row.fix_labels ?? []).filter((label) => label.trim());
  if (labels.length === 0) return null;
  const shown = labels.slice(0, 4);
  const rest = labels.length - shown.length;
  return `Do poprawy (${labels.length}): ${shown.join(", ")}${rest > 0 ? ` i ${rest} więcej` : ""}`;
}

export function transitRemark(row: CvTransitRow): string | null {
  const remark = row.remark?.trim();
  return remark ? `Uwaga: ${remark}` : null;
}

/** D4 (04.10.2026): „Piotr Z. poprawił w screeningu: Motywacja, Stawka”. */
export function transitCardEdit(row: CvTransitRow): string | null {
  const who = row.card_edited_by?.trim();
  if (!who) return null;
  const fields = (row.card_edited_fields ?? []).filter((f) => f.trim());
  return fields.length > 0
    ? `${who} poprawił(a) w screeningu: ${fields.join(", ")}`
    : `${who} poprawił(a) screening`;
}

function dayNumber(date: Date): number {
  return Date.parse(`${warsawToday(date)}T00:00:00Z`) / 86_400_000;
}

/** „dziś”, „wczoraj”, „3 dni temu” — dni kalendarzowe w Europe/Warsaw. */
export function transitAgo(since: string, now: Date = new Date()): string {
  const sinceDate = new Date(since);
  if (Number.isNaN(sinceDate.getTime())) return "dziś";
  const days = Math.round(dayNumber(now) - dayNumber(sinceDate));
  if (days <= 0) return "dziś";
  if (days === 1) return "wczoraj";
  return `${days} dni temu`;
}
