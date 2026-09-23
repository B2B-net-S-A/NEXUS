/**
 * Odznaki karty na Tablicy — Pipeline v4 (decyzja Artura 23.09.2026, makiety
 * https://claude.ai/artifact/JQ8qdz16J6wG24WKTSgv6i).
 *
 * Tablica ma 6 kolumn, więc to, czego nie widać z kolumny, mówi karta:
 * skąd osoba przyszła, kto ją ma na 12 h, że czeka na przegląd DL, za ile
 * poszła do klienta, co się dzieje z rozmową u klienta i czy po zatrudnieniu
 * jest zamówienie. Wszystko liczy się z pól tablicy — tu tylko prezentacja,
 * żadnych reguł, które serwer musiałby powtórzyć.
 */

import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import type { BoardColumnKey } from "@/lib/board-stages";

export type CardBadgeTone =
  | "own"
  | "lock"
  | "free"
  | "reassign"
  | "wait"
  | "ok"
  | "urgent"
  | "info"
  | "neutral"
  | "rate";

export interface CardBadge {
  key: string;
  label: string;
  tone: CardBadgeTone;
  title?: string;
}

export interface CardBadgeContext {
  column: BoardColumnKey | null;
  /** Rekrutacja Nordei — przegląd DL zastępuje ścieżka DZ → Cpro. */
  cproEnabled: boolean;
  viewerId: number | null;
  now: Date;
  /** Odznaka etapu karty — „Z ogłoszenia" z etapu nie powtarza się ze źródła. */
  stageBadge?: string | null;
}

export const CARD_BADGE_TONE_CLASS: Record<CardBadgeTone, string> = {
  own: "bg-primary/15 text-primary",
  lock: "bg-muted text-muted-foreground",
  free: "bg-warning/15 text-warning",
  reassign: "bg-primary/10 text-primary",
  wait: "bg-warning/15 text-warning",
  ok: "bg-success/15 text-success",
  urgent: "bg-destructive/10 text-destructive",
  info: "bg-info/15 text-info",
  neutral: "bg-muted text-muted-foreground",
  rate: "bg-muted text-foreground tabular-nums",
};

const RATE_UNIT_LABEL: Record<string, string> = {
  hourly: "zł/h",
  daily: "zł/MD",
  monthly: "zł/mies.",
};

function firstName(full: string | null | undefined): string {
  return (full ?? "").trim().split(/\s+/)[0] || "ktoś";
}

/** „9 h", „<1 h" — ile zostało blokady. */
export function hoursLeft(until: string, now: Date): string {
  const ms = new Date(until).getTime() - now.getTime();
  if (ms <= 3_600_000) return "<1 h";
  return `${Math.floor(ms / 3_600_000)} h`;
}

function daysLabel(days: number): string {
  if (days <= 0) return "dziś";
  if (days === 1) return "1 dzień";
  return `${days} dni`;
}

export function formatClientRate(item: KanbanItem): string | null {
  if (item.client_rate_value == null || item.client_rate_value === "") return null;
  const value = Number(item.client_rate_value);
  if (!Number.isFinite(value)) return null;
  const unit = RATE_UNIT_LABEL[item.client_rate_unit ?? "hourly"] ?? "zł/h";
  const currency = item.client_rate_currency && item.client_rate_currency !== "PLN"
    ? ` ${item.client_rate_currency}`
    : "";
  const shown = Number.isInteger(value) ? String(value) : value.toFixed(2);
  return `do klienta ${shown}${currency} ${unit}`;
}

function sourceBadge(item: KanbanItem, ctx: CardBadgeContext): CardBadge | null {
  switch (item.entry_source) {
    case "added_manual": {
      const own = item.claim_user_id != null && item.claim_user_id === ctx.viewerId;
      return {
        key: "source",
        label: own ? "Dodałeś sam" : `Dodał(a): ${firstName(item.added_to_job_by_name)}`,
        tone: "neutral",
        title: item.added_to_job_by_name
          ? `Do rekrutacji dodał(a): ${item.added_to_job_by_name}`
          : undefined,
      };
    }
    case "application":
      return { key: "source", label: "Z ogłoszenia", tone: "neutral" };
    case "proposal":
      return { key: "source", label: "Propozycja", tone: "neutral" };
    case "auto_match":
      return { key: "source", label: "Z automatu", tone: "neutral" };
    default:
      return null;
  }
}

function claimBadge(item: KanbanItem, ctx: CardBadgeContext): CardBadge {
  if (item.claim_user_id != null && item.claim_until) {
    const left = hoursLeft(item.claim_until, ctx.now);
    if (item.claim_user_id === ctx.viewerId) {
      return {
        key: "claim",
        label: `Twój · ${left}`,
        tone: "own",
        title: "Masz tę osobę na wyłączność w tej rekrutacji — potem każdy może ją przejąć.",
      };
    }
    return {
      key: "claim",
      label: `${firstName(item.claim_user_name)} · ${left}`,
      tone: "lock",
      title: `Tę osobę prowadzi ${item.claim_user_name ?? "inna osoba"} — do końca blokady nie da się jej ruszyć.`,
    };
  }
  return {
    key: "claim",
    label: "Wolny",
    tone: "free",
    title: "Nikt nie ma tej osoby na wyłączność — „Biorę” daje Ci 12 h.",
  };
}

export function cardBadges(item: KanbanItem, ctx: CardBadgeContext): CardBadge[] {
  const out: CardBadge[] = [];
  const column = ctx.column;
  if (item.entry_source === "reassign") {
    out.push({
      key: "reassign",
      label: item.reassign_from_title
        ? `Przepięcie · ${item.reassign_from_title}`
        : "Przepięcie",
      tone: "reassign",
      title: "Osoba była już wysłana do klienta przy podobnej rekrutacji.",
    });
  }
  if (column === "new") {
    const source = sourceBadge(item, ctx);
    const duplicatesStage = ctx.stageBadge === "posting" && item.entry_source === "application";
    if (source && !duplicatesStage) out.push(source);
    out.push(claimBadge(item, ctx));
  }
  if (column === "verified" && !ctx.cproEnabled) {
    out.push({
      key: "dl_review",
      label: `Czeka na DL · ${daysLabel(item.days_in_stage ?? 0)}`,
      tone: "wait",
      title: "Delivery Lead przegląda osobę i wpisuje stawkę do klienta przed wysłaniem CV.",
    });
  }
  const rate = formatClientRate(item);
  if (
    rate &&
    (column === "cv_sent" ||
      column === "client_interview" ||
      column === "contract" ||
      column === "hired")
  ) {
    out.push({ key: "client_rate", label: rate, tone: "rate" });
  }
  if (column === "cv_sent" && (item.days_in_stage ?? 0) >= 5) {
    out.push({
      key: "client_silence",
      label: `${item.days_in_stage} dni bez odpowiedzi`,
      tone: "wait",
    });
  }
  if (column === "client_interview" && item.interview_badge) {
    const tone = item.interview_badge.tone;
    out.push({
      key: "interview",
      label: item.interview_badge.label,
      tone:
        tone === "urgent" ? "urgent" : tone === "ok" ? "ok" : tone === "wait" ? "wait" : "info",
    });
  }
  if (column === "hired" && item.order_status) {
    out.push(
      item.order_status === "missing"
        ? {
            key: "order",
            label: "Brak zamówienia",
            tone: "urgent",
            title: "Umowa podpisana, ale zamówienia od klienta jeszcze nie ma — Delivery i Finanse dostały powiadomienie.",
          }
        : { key: "order", label: "Zamówienie ✓", tone: "ok" },
    );
  }
  return out;
}

/** Przycisk na karcie w „Nowych": „Biorę" (wolna) / „Przejmij" (cudza, DL). */
export function claimAction(
  item: KanbanItem,
  ctx: CardBadgeContext,
): "take" | "takeover" | null {
  if (ctx.column !== "new" || !item.can_take) return null;
  const heldByOther =
    item.claim_user_id != null && item.claim_user_id !== ctx.viewerId && Boolean(item.claim_until);
  return heldByOther ? "takeover" : "take";
}
