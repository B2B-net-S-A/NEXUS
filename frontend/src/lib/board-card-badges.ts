/**
 * Odznaki karty na Tablicy — Pipeline v4 (decyzja Artura 23.09.2026), od
 * Rekrutacji v5 na 8 kolumnach (makiety
 * https://claude.ai/artifact/CG4mBk9xcHZAn3y9jcmMeW).
 *
 * To, czego nie widać z kolumny, mówi karta:
 * skąd osoba przyszła, kto ją ma na 12 h, że czeka na przegląd DL, za ile
 * poszła do klienta, co się dzieje z rozmową u klienta i czy po zatrudnieniu
 * jest zamówienie. Wszystko liczy się z pól tablicy — tu tylko prezentacja,
 * żadnych reguł, które serwer musiałby powtórzyć.
 */

import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import type { BoardColumnKey } from "@/lib/board-stages";
import { cardBadgeLabel } from "@/lib/candidate-followup";

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

/** 0370: podpowiedź do odznak prepów — ruch karty nie jest blokowany. */
const PREP_BADGE_TITLE: Partial<Record<string, string>> = {
  prep_missing:
    "Przed rozmową u klienta brakuje prepu z kandydatem (Prep 1 — Delivery Lead, Prep 2 — rekruter). Umów go w kalendarzu „Rozmowy u klienta”.",
  prep_weak:
    "Prep odbył się, ale wypadł słabo (transkrypt z Teams). Warto umówić jeszcze jedną rozmowę przed spotkaniem u klienta.",
};

export interface CardBadgeContext {
  column: BoardColumnKey | null;
  /** Rekrutacja Nordei — przegląd DL zastępuje kolejka Cpro. */
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
  if (column === "new" || column === "screening") {
    const source = sourceBadge(item, ctx);
    const duplicatesStage = ctx.stageBadge === "posting" && item.entry_source === "application";
    if (source && !duplicatesStage) out.push(source);
    out.push(claimBadge(item, ctx));
  }
  // Przegląd DL (Rekrutacja v5): osoby w „QC CV" poza Nordeą — Delivery Lead
  // sprawdza CV, wpisuje stawkę do klienta i wysyła.
  // DL czeka dopiero na CV, które przeszło QC (albo przepuszczone) — przy
  // niesprawdzonym lub niezaliczonym QC ruch ma rekruter.
  const qcDone = item.qc?.status === "passed" || item.qc?.status === "overridden";
  if (column === "cv_qc" && !ctx.cproEnabled && qcDone) {
    out.push({
      key: "dl_review",
      label: `Czeka na DL · ${daysLabel(item.days_in_stage ?? 0)}`,
      tone: "wait",
      title: "Delivery Lead przegląda CV i wpisuje stawkę do klienta przed wysłaniem.",
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
  // 0372: follow-up z kandydatem, gdy klient milczy — kto dzwoni (jeden
  // telefon na OSOBĘ, także gdy jest w kilku procesach). Tylko termin do
  // jutra: plakietka „za 9 dni” byłaby szumem na każdej karcie.
  if (
    (column === "cv_sent" || column === "client_interview") &&
    item.followup &&
    item.followup.state !== "scheduled"
  ) {
    const f = item.followup;
    out.push({
      key: "followup",
      label: cardBadgeLabel(f, ctx.viewerId),
      tone: f.state === "overdue" ? "urgent" : f.state === "today" ? "wait" : "neutral",
      title:
        f.process_count > 1
          ? `Kandydat czeka na klienta w ${f.process_count} procesach — dzwoni jedna osoba i mówi o wszystkich.`
          : "Klient milczy od 14 dni — telefon do kandydata, że dalej jest w procesie.",
    });
  }
  // Odznaka rozmowy stoi w KAŻDEJ kolumnie: do 24.09.2026 tylko w „Rozmowie
  // u klienta”, więc osoba przesunięta dalej (np. na „Umowę”) z zaległym
  // telefonem po rozmowie wyglądała na załatwioną.
  if (item.interview_badge) {
    const { kind, tone } = item.interview_badge;
    const title = PREP_BADGE_TITLE[kind];
    out.push({
      key: "interview",
      label: item.interview_badge.label,
      tone:
        tone === "urgent" ? "urgent" : tone === "ok" ? "ok" : tone === "wait" ? "wait" : "info",
      ...(title ? { title } : {}),
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

/** Przycisk na karcie w „Nowych"/„Screeningu": „Biorę" (wolna) / „Przejmij" (cudza, DL). */
export function claimAction(
  item: KanbanItem,
  ctx: CardBadgeContext,
): "take" | "takeover" | null {
  if ((ctx.column !== "new" && ctx.column !== "screening") || !item.can_take) return null;
  const heldByOther =
    item.claim_user_id != null && item.claim_user_id !== ctx.viewerId && Boolean(item.claim_until);
  return heldByOther ? "takeover" : "take";
}

// ── Rekrutacja v5: chip QC, strzałka „→" i „kto ma ruch" na karcie ─────────

export type QcChipTone = "ok" | "urgent" | "wait" | "neutral";

export interface QcChip {
  label: string;
  tone: QcChipTone;
  title: string;
}

/** Chip QC na karcie w kolumnie „QC CV" (`item.qc` z tablicy). */
export function qcChip(item: KanbanItem): QcChip {
  const qc = item.qc ?? null;
  if (!qc || qc.status === "unchecked") {
    return {
      label: "QC nie sprawdzone",
      tone: "neutral",
      title: "Nikt jeszcze nie uruchomił kontroli CV — kliknij, żeby sprawdzić.",
    };
  }
  if (qc.status === "passed") {
    return { label: "QC ✓", tone: "ok", title: "CV przeszło kontrolę przed wysłaniem." };
  }
  if (qc.status === "overridden") {
    return {
      label: "QC przepuszczone",
      tone: "wait",
      title: "Delivery Lead albo admin przepuścił CV mimo uwag QC (z powodem).",
    };
  }
  const n = qc.blocking_failed;
  return {
    label: `QC: ${n} do poprawy`,
    tone: "urgent",
    title: "CV ma braki, które blokują wysłanie — kliknij, żeby zobaczyć poprawki.",
  };
}

/**
 * Znany z karty brak przed przejściem do NASTĘPNEJ kolumny — strzałka jest
 * wtedy szara (ale klikalna: okno „Przesuń dalej" mówi, co zrobić). `null` =
 * karta nie zna braku; pełną listę liczy serwer w oknie.
 */
export function knownForwardGap(
  item: KanbanItem,
  from: BoardColumnKey | null,
): string | null {
  if (from === "screening" && item.screening_done === false) {
    return "Brak arkusza screeningu";
  }
  if (from === "cv_qc" && item.qc?.status === "failed") {
    return `QC: ${item.qc.blocking_failed} do poprawy`;
  }
  return null;
}

export interface CardNextStep {
  /** „Twój ruch", imię rekrutera, „DL", „Klient"… — kto ma ruch. */
  who: string;
  /** Ruch należy do patrzącego (podświetlenie tokenem primary). */
  mine: boolean;
  label: string;
}

/** Plakietka ruchu patrzącego (24.09.2026: „Ty" czytało się jak etykieta osoby). */
export const MY_MOVE_LABEL = "Twój ruch";

const ROLE_WHO: Record<string, string> = {
  client: "Klient",
  candidate: "Kandydat",
  delivery: "Delivery",
};

function firstNameOrNull(full: string | null | undefined): string | null {
  const name = full?.trim();
  return name ? name.split(/\s+/)[0] : null;
}

/**
 * Ruch po naszej stronie (rekruter / przegląd): czyj? Blokada „Biorę" w Nowych
 * wygrywa z rekruterem karty; bez obu albo gdy to patrzący — „Twój ruch".
 * Bez `viewerId` (harness, starszy kontekst) zostaje „Twój ruch", jak dawne „Ty".
 */
function recruiterSideWho(
  item: KanbanItem,
  owner: string,
  viewerId: number | null | undefined,
): { who: string; mine: boolean } {
  const claimActive = owner === "review" && item.claim_user_id != null;
  const personId = claimActive ? item.claim_user_id : (item.recruiter_id ?? null);
  const personName = claimActive ? item.claim_user_name : item.recruiter_name;
  if (personId == null || viewerId == null || personId === viewerId) {
    return { who: MY_MOVE_LABEL, mine: true };
  }
  const name = firstNameOrNull(personName);
  return name ? { who: name, mine: false } : { who: MY_MOVE_LABEL, mine: true };
}

/**
 * Dół karty: kto ma ruch i co zrobić. Opiera się na `nextActionFor` (lustro
 * backendu), a w kolumnie „QC CV" — której tamta reguła nie zna w szczegółach
 * (wynik QC, kolejka Cpro) — mówi, czy ruch jest po stronie rekrutera
 * (poprawki), Delivery Leada (przegląd i wysłanie poza Nordeą) czy osoby od Cpro.
 */
export function cardNextStep(
  action: { label: string; owner: string; kind: string },
  item: KanbanItem,
  ctx: {
    column: BoardColumnKey | null;
    cproEnabled: boolean;
    stageBadge?: string | null;
    /** Patrzący — „Twój ruch" tylko wtedy, gdy karta jest jego (albo niczyja). */
    viewerId?: number | null;
  },
): CardNextStep | null {
  const recruiter = () => recruiterSideWho(item, "recruiter", ctx.viewerId);
  if (ctx.column === "cv_qc") {
    if (item.qc?.status === "failed") {
      return { ...recruiter(), label: "Popraw CV wg QC" };
    }
    if (ctx.stageBadge !== "cpro" && item.qc?.status !== "passed" && item.qc?.status !== "overridden") {
      return { ...recruiter(), label: "Sprawdź QC CV" };
    }
    if (ctx.cproEnabled) {
      return ctx.stageBadge === "cpro"
        ? { who: "Osoba od Cpro", mine: false, label: "Wrzuć CV do Cpro" }
        : { ...recruiter(), label: "Przekaż do Cpro" };
    }
    return { who: "DL", mine: false, label: "Przegląd CV i wysłanie do klienta" };
  }
  if (action.kind === "none" || action.owner === "none" || !action.label) return null;
  const role = ROLE_WHO[action.owner];
  if (role) return { who: role, mine: false, label: action.label };
  return { ...recruiterSideWho(item, action.owner, ctx.viewerId), label: action.label };
}
