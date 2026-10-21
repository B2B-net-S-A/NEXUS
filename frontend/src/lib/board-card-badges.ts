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

import { boardCardBadge } from "@/lib/recommendation-card";
import { agreementBadge } from "@/lib/b2b-agreement";
import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import type { BoardColumnKey, StageBadgeKey } from "@/lib/board-stages";
import { cardBadgeLabel } from "@/lib/candidate-followup";
import { WHY_CANDIDATE_LABEL } from "@/lib/pipeline-next-action";
import { autoMatchBadgeLabel, autoMatchBadgeTitle } from "@/lib/candidate-notes-view";
import { qcCountsText } from "@/lib/cv-qc";
import { rateArrowLine, rateChangeBadgeText } from "@/lib/rate-change";
import { warsawToday } from "@/lib/warsaw-date";
import { addedToBaseTitle, addedToBaseView, newInBaseDaysText } from "@/lib/added-to-base";
import { offLimitsConfirmedDay } from "@/lib/off-limits";

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
  | "rate"
  | "champion";

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
  prep2_skipped:
    "Rozmowa odbędzie się bez Prepu 2 — powód zapisał rekruter. Zamiast prepu jest krótki telefon do kandydata przed rozmową.",
  prep_refused:
    "Kandydat odrzucił zaproszenie na prep albo zaproponował inny termin. Przyjmij jego termin albo przełóż prep w panelu osoby.",
};

export interface CardBadgeContext {
  column: BoardColumnKey | null;
  /** Rekrutacja Nordei — przegląd DL kończy akceptacja do kolejki Cpro
   *  (13.10.2026), nie wysyłka do klienta. */
  cproEnabled: boolean;
  viewerId: number | null;
  now: Date;
  /** Odznaka etapu karty — „Z ogłoszenia" z etapu nie powtarza się ze źródła. */
  stageBadge?: string | null;
  /** Przegląd przed wysłaniem do klienta w tej rekrutacji należy do patrzącego
   *  (serwer: `viewer_owns_dl_review`) — „Czeka na Ciebie” zamiast „Czeka na DL”. */
  viewerOwnsDlReview?: boolean;
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
  // Championi (D3, 15.10.2026): ten sam złoty kolor co status w nagłówku.
  champion: "bg-medal-gold text-medal-gold-foreground",
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

/** „dziś”, „1 dzień”, „3 dni” — ile osoba czeka (plakietki karty). */
export function daysLabel(days: number): string {
  if (days <= 0) return "dziś";
  if (days === 1) return "1 dzień";
  return `${days} dni`;
}

// ── „Do wysłania do klienta” (13.10.2026) ───────────────────────────────────

const DAY_MS = 86_400_000;

/**
 * Karta czeka na Delivery Leada: kolumna „QC CV”, karta nie stoi już
 * w kolejce Cpro, a CV przeszło QC albo ktoś je przepuścił. Poza Nordeą DL
 * wysyła do klienta, u Nordei akceptuje do kolejki Cpro (13.10.2026). Przy
 * niesprawdzonym lub niezaliczonym QC ruch ma rekruter.
 */
export function isReadyForDlSend(
  item: KanbanItem,
  column: BoardColumnKey | null,
  inCproQueue: boolean,
): boolean {
  if (column !== "cv_qc" || inCproQueue) return false;
  return item.qc?.status === "passed" || item.qc?.status === "overridden";
}

/**
 * Gotowa karta liczy się do „Czeka na Ciebie”, „Twój ruch” i „Przejrzyj po
 * kolei” — lustro `dl_send_queue.counts_for_reviewer`. Karta z importu Traffita
 * i karta nieopublikowanej rekrutacji stoją poza licznikami pasa „Do wysłania
 * do klienta” (serwer: `dl_send_counts: false`, audyt 13.10.2026); przegląd
 * dalej da się otworzyć. Starszy serwer bez pola — jak dotąd.
 */
export function countsForDlReview(
  item: KanbanItem,
  column: BoardColumnKey | null,
  inCproQueue: boolean,
): boolean {
  return isReadyForDlSend(item, column, inCproQueue) && item.dl_send_counts !== false;
}

function timeOf(value: string | null | undefined): number | null {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? null : ms;
}

/**
 * Od kiedy karta jest gotowa do wysłania: późniejsze z wejścia do kolumny
 * i zaliczenia QC — karta bywa w „QC CV” kilka dni, zanim QC przejdzie.
 * `null` = tablica nie zna którejś z dat (starszy serwer).
 */
export function dlReadySince(item: KanbanItem): number | null {
  const moved = timeOf(item.moved_at);
  const ok = timeOf(item.qc?.ok_at);
  return moved == null || ok == null ? null : Math.max(moved, ok);
}

/** Dni KALENDARZOWE w Europe/Warsaw od gotowości — ta sama arytmetyka co
 *  `waitingFor` (`lib/api/boardTasks.ts`); bez dat zostają dni na etapie. */
export function dlWaitingDays(item: KanbanItem, now: Date): number {
  const since = dlReadySince(item);
  if (since == null) return item.days_in_stage ?? 0;
  const dayNumber = (d: Date) => Date.parse(`${warsawToday(d)}T00:00:00Z`) / DAY_MS;
  return Math.max(0, Math.round(dayNumber(now) - dayNumber(new Date(since))));
}

/**
 * Kolejka przeglądu „po kolei” z kart kolumny „QC CV”: tylko gotowe do
 * wysłania (u Nordei — do akceptacji), najdłużej czekające pierwsze. Karty
 * w kolejce Cpro (ta sama kolumna, znacznik „W kolejce Cpro”) czekają już
 * na osobę od Cpro; karty z importu Traffita — poza kolejką, jak w pasie
 * na pulpicie (`countsForDlReview`).
 */
export function dlSendQueue(
  qcColumnItems: readonly KanbanItem[],
  inCproQueue: (item: KanbanItem) => boolean,
  now: Date,
): KanbanItem[] {
  const since = (item: KanbanItem) =>
    dlReadySince(item) ?? now.getTime() - (item.days_in_stage ?? 0) * DAY_MS;
  return qcColumnItems
    .filter((item) => countsForDlReview(item, "cv_qc", inCproQueue(item)))
    .sort((a, b) => since(a) - since(b));
}

/** „od dziś”, „od 1 dnia”, „od 3 dni”. */
function sinceLabel(days: number): string {
  if (days <= 0) return "od dziś";
  if (days === 1) return "od 1 dnia";
  return `od ${days} dni`;
}

export interface DlWaitingStatus {
  /** Osoba jest już w kolejce Delivery Leada (QC zdane albo przepuszczone). */
  ready: boolean;
  text: string;
}

/**
 * Osoba stoi w „QC CV” i dalej prowadzi ją Delivery Lead (14.10.2026): okno
 * „Przesuń dalej” i ramka „Następny etap” mówią, od kiedy czeka — albo co
 * rekruter musi jeszcze zrobić, zanim DL ją zobaczy (kolejka DL liczy tylko
 * gotowe karty). Do tej daty był tu przycisk z toastem o kolejce „Czeka na
 * Ciebie”, której rekruter nie ma. Bez karty (starszy wołający) — zdanie,
 * które jest prawdą zawsze.
 */
export function dlWaitingStatus(item: KanbanItem | null | undefined, now: Date): DlWaitingStatus {
  if (!item) {
    return { ready: false, text: "Osoba jest w „QC CV” — trafi do Delivery Leada, gdy QC przejdzie." };
  }
  if (isReadyForDlSend(item, "cv_qc", false)) {
    return { ready: true, text: `Czeka u Delivery Leada ${sinceLabel(dlWaitingDays(item, now))}.` };
  }
  if (item.qc?.status === "failed") {
    return {
      ready: false,
      text: `QC: ${item.qc.blocking_failed} do poprawy — popraw CV, zanim Delivery Lead je zobaczy.`,
    };
  }
  return {
    ready: false,
    text: "QC jeszcze nie sprawdzone — sprawdź CV, zanim Delivery Lead je zobaczy.",
  };
}

// ── Stan CV firmowego na karcie (14.10.2026) ────────────────────────────────

/**
 * Jedna plakietka o CV firmowym — karta Tablicy i wiersz tabeli osób:
 * automat jeszcze pisze CV, CV jest i QC już je sprawdziło (ile do poprawy
 * i ile uwag — osobno, jak w panelu osoby, 18.10.2026; przepuszczone QC mówi
 * „przepuszczone”, nie „do poprawy”), albo gotowe auto-CV czeka na
 * przegląd (QC jeszcze nie biegło). Liczba mówi „QC:” (14.10.2026): karta CV
 * liczy więcej — QC, uwagi generatora i kontrolę AI („N rzeczy do
 * sprawdzenia”), a goła liczba dawała na jednym ekranie dwie różne wartości
 * (rekrutacja 789128: plakietka 1, karta 8). Wynik QC pokazujemy tylko na
 * „Zweryfikowanym” — w „QC CV” mówi o nim chip QC. `=== true`: odznaka
 * obiecuje gotowy dokument, więc brak pola (starszy serwer) jej nie daje.
 */
export function cvStateBadge(item: KanbanItem, column: BoardColumnKey | null): CardBadge | null {
  if (item.auto_cv_state === "processing") {
    return {
      key: "cv_state",
      label: "CV w przygotowaniu…",
      tone: "neutral",
      title: "Automat przygotowuje CV firmowe po weryfikacji — za chwilę będzie w sekcji CV.",
    };
  }
  const qc = item.qc ?? null;
  const qcRan = qc?.status === "passed" || qc?.status === "failed" || qc?.status === "overridden";
  const hasCompanyCv =
    item.company_cv === true || (item.company_cv == null && item.auto_cv_ready === true);
  if (column === "verified" && hasCompanyCv && qc && qcRan) {
    if (qc.status === "overridden") {
      return {
        key: "cv_state",
        label: "CV gotowe · QC przepuszczone",
        tone: "ok",
        title:
          "CV firmowe jest gotowe, a QC zostało przepuszczone mimo uwag. Uwagi nadal widać w karcie CV.",
      };
    }
    const blocking = qc.blocking_failed;
    const warnings = qc.warnings_count ?? 0;
    return blocking + warnings > 0
      ? {
          key: "cv_state",
          label: `CV gotowe · QC: ${qcCountsText(blocking, warnings)}`,
          tone: blocking > 0 ? "wait" : "info",
          title:
            blocking > 0
              ? "CV firmowe jest gotowe, a QC znalazło rzeczy do poprawy przed wysłaniem. Uwagi nie blokują. Pełna lista (z uwagami generatora i kontrolą AI) jest w karcie CV."
              : "CV firmowe jest gotowe, QC nie blokuje — zostały uwagi do decyzji. Pełna lista (z uwagami generatora i kontrolą AI) jest w karcie CV.",
        }
      : {
          key: "cv_state",
          label: "CV gotowe · QC bez uwag",
          tone: "ok",
          title:
            "CV firmowe jest gotowe i QC nie ma uwag. Uwagi generatora i kontrolę AI pokazuje karta CV.",
        };
  }
  if (item.auto_cv_ready === true) {
    return {
      key: "cv_state",
      label: "CV gotowe w tle",
      tone: "info",
      title: "CV wygenerowane automatycznie po weryfikacji czeka w warsztacie CV — sprawdź je przed wysyłką.",
    };
  }
  return null;
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

/**
 * 0404: zgłoszenie z linku rekrutacji po przeglądzie AI. Werdykt liczy serwer
 * (`services/application_screening.py`); tu tylko etykieta. „Dodaj mimo to”
 * (osoba odrzucona przez AI, dodana ręcznie) mówi to wprost.
 */
export function aiScreeningBadge(
  meta: KanbanItem["entry_ai_screening"],
): { label: string; tone: CardBadgeTone; title: string } | null {
  if (!meta) return null;
  const must =
    meta.must_total != null && meta.must_total > 0
      ? ` Must-have w CV: ${meta.must_found ?? 0} z ${meta.must_total}.`
      : "";
  if (meta.overridden) {
    return {
      label: "AI: odrzucony · dodany ręcznie",
      tone: "neutral",
      title: `Zgłoszenie z ogłoszenia. AI uznało je za niepasujące, ktoś dodał osobę mimo to.${must}`,
    };
  }
  if (!meta.assessed) {
    return {
      label: "AI nie oceniło",
      tone: "info",
      title: `Zgłoszenie z ogłoszenia. AI nie oceniło CV (brak czytelnego CV albo awaria) — sprawdź sam.${must}`,
    };
  }
  if (meta.verdict === "fits") {
    return {
      label: "AI: pasuje",
      tone: "ok",
      title: `Zgłoszenie z ogłoszenia. AI: doświadczenie pasuje do roli.${must}`,
    };
  }
  return {
    label: "AI: do sprawdzenia",
    tone: "info",
    title: `Zgłoszenie z ogłoszenia. AI nie jest pewne dopasowania — sprawdź CV.${must}`,
  };
}

/**
 * Etap 2 linków (19.10.2026): osoba zgłosiła się z linku rekrutacji — karta
 * mówi napisem, czyj to link (plakietka źródła jest ikoną z dymkiem).
 */
function linkOwnerBadge(item: KanbanItem, ctx: CardBadgeContext): CardBadge | null {
  if (item.entry_source !== "application" || item.entry_link_owner_id == null) return null;
  const own = item.entry_link_owner_id === ctx.viewerId;
  return {
    key: "link",
    label: own ? "Z Twojego linku" : `Z linku: ${firstName(item.entry_link_owner_name)}`,
    tone: "neutral",
    title: own
      ? "Osoba zgłosiła się z Twojego linku do tej rekrutacji."
      : `Osoba zgłosiła się z linku, który udostępnił(a) ${item.entry_link_owner_name ?? "ktoś z zespołu"}.`,
  };
}

/**
 * Osoba była już w rekrutacji i zgłosiła się ponownie z czyjegoś linku —
 * karta i blokada prowadzącego bez zmian, ślad zostaje na karcie (makieta 2a,
 * 19.10.2026). Własny link wygrywa w napisie, reszta jest w podpowiedzi.
 */
function reappliedViaLinkBadge(item: KanbanItem, ctx: CardBadgeContext): CardBadge | null {
  const owners = item.reapplied_via_links ?? [];
  if (owners.length === 0) return null;
  const own = owners.some((o) => o.owner_id === ctx.viewerId);
  const others = owners.filter((o) => o.owner_id !== ctx.viewerId);
  const sources = [
    ...(own ? ["z Twojego linku"] : []),
    ...others.map((o) => `z linku, który udostępnił(a) ${o.owner_name ?? "ktoś z zespołu"}`),
  ].join(" i ");
  return {
    key: "link_reapplied",
    label: own
      ? "Zgłosił się też z Twojego linku"
      : `Zgłosił się też z linku: ${others.map((o) => firstName(o.owner_name)).join(", ")}`,
    tone: "neutral",
    title: `Osoba była już w tej rekrutacji i zgłosiła się ponownie ${sources}. Karta bez zmian, nowe CV jest w profilu.`,
  };
}

/**
 * Off-limits (21.10.2026): osoba z firmy, z której nie wyciągamy ludzi,
 * dodana po potwierdzeniu w oknie „Czy sam(a) się do nas zgłosił(a)?”.
 * Plakietka w każdej kolumnie — to ślad dla klienta, nie stan procesu.
 */
export function offLimitsCardBadge(meta: KanbanItem["entry_off_limits"]): CardBadge | null {
  if (!meta) return null;
  const day = offLimitsConfirmedDay(meta.confirmed_at);
  const who = [meta.confirmed_by_name, day].filter(Boolean).join(", ");
  return {
    key: "off_limits",
    label:
      meta.how === "left_company" ? "Off-limits · już tam nie pracuje" : "Off-limits · sam(a) się zgłosił(a)",
    tone: "wait",
    title: `${meta.client_name}: stamtąd nie wyciągamy ludzi. ${meta.how_label}${who ? ` — potwierdził(a) ${who}` : ""}.`,
  };
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
    case "application": {
      const ai = aiScreeningBadge(item.entry_ai_screening);
      if (ai) return { key: "source", label: ai.label, tone: ai.tone, title: ai.title };
      // Zgłoszenie z linku bez przeglądu AI: źródło mówi plakietka linku.
      return item.entry_link_owner_id != null
        ? null
        : { key: "source", label: "Z ogłoszenia", tone: "neutral" };
    }
    case "proposal":
      return { key: "source", label: "Propozycja", tone: "neutral" };
    case "auto_match":
      return {
        key: "source",
        label: autoMatchBadgeLabel(item.entry_auto_match) ?? "Z automatu",
        tone: "neutral",
        title: autoMatchBadgeTitle(item.entry_auto_match),
      };
    default:
      return null;
  }
}

/**
 * Runda 10 (F04): znacznik etapu „Z ogłoszenia" tylko wtedy, gdy osoba
 * naprawdę przyszła z ogłoszenia. Ręczne dodanie też ląduje na etapie
 * „Ogłoszenia" szablonu, a karta mówiła wtedy „Z ogłoszenia" obok „Dodałeś
 * sam". Źródło nieznane (proces sprzed 0352) zostawia dawny znacznik.
 */
export function cardStageBadge(
  item: Pick<KanbanItem, "entry_source">,
  badge: StageBadgeKey | null | undefined,
): StageBadgeKey | null {
  if (!badge) return null;
  if (badge === "posting" && item.entry_source && item.entry_source !== "application") {
    return null;
  }
  return badge;
}

/**
 * „W bazie od” (13.10.2026): osoba dodana do bazy w ostatnich 14 dniach —
 * rekruter wybiera w „Nowych” najpierw świeże osoby. Źródło i blokada są na
 * karcie ikonami, więc to krótki napis; pełna data i autor w dymku.
 */
function newInBaseBadge(item: KanbanItem, ctx: CardBadgeContext): CardBadge | null {
  const view = addedToBaseView(
    { at: item.candidate_added_at, exact: item.candidate_added_exact },
    ctx.now,
  );
  if (!view?.isNew || view.days == null) return null;
  return {
    key: "new_in_base",
    label: `Nowy · ${newInBaseDaysText(view.days)}`,
    tone: "info",
    title: addedToBaseTitle(view, item.candidate_added_by_name),
  };
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
  // Champion pierwszy (D3, 15.10.2026) — oznacza go Delivery Lead w nagłówku
  // rekrutacji, karta tylko to pokazuje.
  if (item.is_champion) {
    out.push({
      key: "champion",
      label: "Champion",
      tone: "champion",
      title: "Champion tej rekrutacji — oznaczył Delivery Lead.",
    });
  }
  if (item.entry_source === "reassign") {
    out.push({
      key: "reassign",
      // Numer rekrutacji („ZOB-1725”) jest krótszy i jednoznaczny; tytuł
      // zostaje, gdy rekrutacja numeru nie ma (np. założona w NEXUSIE).
      label: item.reassign_from_reference
        ? `↻ z ${item.reassign_from_reference}`
        : item.reassign_from_title
          ? `Przepięcie · ${item.reassign_from_title}`
          : "Przepięcie",
      tone: "reassign",
      title: item.reassign_from_title
        ? `Osoba była już wysłana do klienta przy podobnej rekrutacji: ${item.reassign_from_title}.`
        : "Osoba była już wysłana do klienta przy podobnej rekrutacji.",
    });
  }
  const offLimits = offLimitsCardBadge(item.entry_off_limits);
  if (offLimits) out.push(offLimits);
  if (column === "new" || column === "screening") {
    const link = linkOwnerBadge(item, ctx);
    if (link) out.push(link);
    const reapplied = reappliedViaLinkBadge(item, ctx);
    if (reapplied) out.push(reapplied);
    const source = sourceBadge(item, ctx);
    const duplicatesStage = ctx.stageBadge === "posting" && item.entry_source === "application";
    if (source && !duplicatesStage) out.push(source);
    out.push(claimBadge(item, ctx));
    const fresh = newInBaseBadge(item, ctx);
    if (fresh) out.push(fresh);
  }
  // Przegląd DL (Rekrutacja v5): osoby w „QC CV" poza Nordeą — Delivery Lead
  // sprawdza CV, wpisuje stawkę do klienta i wysyła.
  // DL czeka dopiero na CV, które przeszło QC (albo przepuszczone) — przy
  // niesprawdzonym lub niezaliczonym QC ruch ma rekruter. Dni liczą się od
  // gotowości, nie od wejścia do kolumny; Delivery Lead tej rekrutacji czyta
  // „Czeka na Ciebie” (13.10.2026).
  if (countsForDlReview(item, column, ctx.stageBadge === "cpro")) {
    const waited = daysLabel(dlWaitingDays(item, ctx.now));
    out.push(
      ctx.viewerOwnsDlReview
        ? {
            key: "dl_review",
            label: `Czeka na Ciebie · ${waited}`,
            tone: "wait",
            title: ctx.cproEnabled
              ? "Przejrzyj CV, wpisz stawkę do Cpro i zaakceptuj do kolejki Cpro."
              : "Przejrzyj CV, wpisz stawkę do klienta i wyślij.",
          }
        : {
            key: "dl_review",
            label: `Czeka na DL · ${waited}`,
            tone: "wait",
            title: ctx.cproEnabled
              ? "Delivery Lead przegląda CV, wpisuje stawkę do Cpro i akceptuje osobę do kolejki Cpro."
              : "Delivery Lead przegląda CV i wpisuje stawkę do klienta przed wysłaniem.",
          },
    );
  }
  // 0413: stan karty rekomendacji — braki są informacją, nic nie blokują.
  const cardBadge = boardCardBadge(item.card, item.contact_attempts ?? 0, column);
  if (cardBadge && item.card !== undefined) {
    out.push({ key: "recommendation_card", ...cardBadge });
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
  // 0418: kandydat zmienił stawkę w trakcie procesu — plakietka do zamknięcia
  // sprawy (decyzja DL albo wynik negocjacji), w każdej kolumnie.
  if (item.rate_change) {
    const rc = item.rate_change;
    const arrow = rateArrowLine(rc);
    out.push({
      key: "rate_change",
      label: arrow ? `${arrow} · ${rateChangeBadgeText(rc)}` : rateChangeBadgeText(rc),
      tone: rc.status === "agreed" ? "ok" : rc.status === "negotiating" ? "info" : "wait",
      title:
        "Kandydat zmienił stawkę w trakcie procesu. Szczegóły i historia w panelu osoby.",
    });
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
  // 04.10.2026: stan umowy z Generatora w każdej kolumnie — co trzecia umowa
  // powstaje jeszcze w „Rozmowie u klienta”.
  const agreement = agreementBadge(item.agreement, ctx.now);
  if (agreement) {
    out.push({
      key: "agreement",
      label: agreement.label,
      tone: agreement.tone === "success" ? "ok" : agreement.tone === "warning" ? "wait" : "info",
      title: agreement.title,
    });
  }
  // 17.10.2026: „Pracuje u nas” daje wyłącznie umowa w Kontraktach — karta
  // na „Zatrudniony” bez umowy mówi, czego brakuje (przed zamówieniem).
  if (column === "hired" && item.missing_contract) {
    out.push({
      key: "contract",
      label: "Brak umowy w Kontraktach",
      tone: "wait",
      title:
        "Karta jest na „Zatrudniony”, ale w Kontraktach nie ma umowy tej osoby u klienta. „Pracuje u nas” pojawi się po wpisaniu umowy — Delivery Lead klienta dostał przypomnienie.",
    });
  }
  // 20.10.2026: czerwone „Brak zamówienia” czytało się jak warunek
  // zatrudnienia. Zamówienie to krok Delivery Leada i Finansów po fakcie —
  // plakietka mówi, u kogo jest, i nie krzyczy.
  if (column === "hired" && item.order_status) {
    out.push(
      item.order_status === "missing"
        ? {
            key: "order",
            label: "Zamówienie: u Delivery Leada",
            tone: "neutral",
            title:
              "Zatrudnienie jest zapisane. Zamówienie od klienta uzupełnia Delivery Lead i Finanse — mają jedną sprawę „uzupełnij zamówienie”. Zamówienie nie jest warunkiem zatrudnienia.",
          }
        : { key: "order", label: "Zamówienie ✓", tone: "ok" },
    );
  }
  return out;
}

/**
 * PR 4 ścieżki kandydata (04.10.2026): źródło, blokada 12 h i stan karty
 * rekomendacji to ikony z krótkim dopiskiem — pełna treść w podpowiedzi
 * i w panelu osoby. Karta ma mówić przede wszystkim, czyj jest ruch.
 * `null` = plakietka zostaje pełnym napisem.
 */
export interface CompactCardBadge {
  /** Krótki dopisek obok ikony (`null` = sama ikona). */
  short: string | null;
  /** Pełna treść dla podpowiedzi i czytników ekranu. */
  full: string;
}

export const COMPACT_BADGE_KEYS: ReadonlySet<string> = new Set([
  "source",
  "claim",
  "recommendation_card",
]);

export function compactCardBadge(badge: CardBadge): CompactCardBadge | null {
  if (!COMPACT_BADGE_KEYS.has(badge.key)) return null;
  const full = badge.title ? `${badge.label} — ${badge.title}` : badge.label;
  if (badge.key === "claim") {
    // „Twój · 11 h” → „11 h” (kolor mówi „mój”); cudza blokada zostaje
    // z imieniem („Anna · 3 h”); „Wolny” → sama ikona.
    if (badge.tone === "lock") return { short: badge.label, full };
    if (badge.tone === "own") return { short: badge.label.split(" · ")[1] ?? null, full };
    return { short: null, full };
  }
  if (badge.key === "recommendation_card") {
    // „2 próby kontaktu” zostaje napisem — to informacja o telefonach, nie o karcie.
    if (/^\d/.test(badge.label)) return null;
    const missing = /brakuje (\d+)/.exec(badge.label);
    if (missing) return { short: `−${missing[1]}`, full };
    return { short: badge.tone === "ok" ? "✓" : null, full };
  }
  return { short: null, full };
}

/**
 * Krytyczne bez śladu w profilu, CV i notatkach (16.10.2026). Do tego dnia
 * taka osoba traciła na Tablicy pierścień dopasowania bez słowa wyjaśnienia,
 * bo wynik liczył się z bramką wyszukiwania. Teraz wynik jest, a karta mówi,
 * czego brakuje. Informacja, nie blokada — ruchu karty nie dotyka.
 */
export function criticalGapBadge(
  gaps: readonly string[] | null | undefined,
): { label: string; title: string } | null {
  const names = (gaps ?? []).map((g) => g.trim()).filter(Boolean);
  if (names.length === 0) return null;
  const list = names.join(", ");
  return {
    label: `brak: ${list}`,
    title:
      `${names.length === 1 ? "Wymaganie krytyczne" : "Wymagania krytyczne"} bez śladu ` +
      `w profilu, CV i notatkach: ${list}. Wyszukiwanie nie pokazuje tej osoby; ` +
      "tu wynik dopasowania zostaje. Sprawdź w rozmowie albo dopisz w profilu.",
  };
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
    return item.screening_requirement === "why_candidate"
      ? "Brak „Dlaczego ten kandydat”"
      : "Brak arkusza screeningu";
  }
  // Minimum dla Delivery Leada (21.10.2026) — bramka „Zweryfikowany”.
  if (from === "screening" && minimumOnlyGap(item)) {
    return `Brak: ${item.minimum_missing!.map(minimumFieldShortLabel).join(", ")}`;
  }
  // 14.10.2026: bez CV firmowego przeciągnięcie na „QC CV” wkładało osobę
  // wprost do kolejki Delivery Leada. `null`/brak pola = nie wiadomo.
  if (from === "verified" && item.company_cv === false) {
    return "Brak CV firmowego";
  }
  if (from === "cv_qc" && item.qc?.status === "failed") {
    return `QC: ${item.qc.blocking_failed} do poprawy`;
  }
  return null;
}

const MINIMUM_SHORT_LABEL: Readonly<Record<string, string>> = {
  location: "lokalizacja",
  work_mode: "tryb pracy",
  availability: "dostępność",
  recommendation: "„Dlaczego”",
  motivation: "motywacja",
  worked_at_client: "praca u klienta",
  english: "angielski",
  nationality: "narodowość",
  red_flags: "red flags",
};

/** Krótka nazwa pola minimum na karcie Tablicy (kolumna ma ~200 px przy 1280). */
export function minimumFieldShortLabel(key: string): string {
  return MINIMUM_SHORT_LABEL[key] ?? key;
}

/**
 * Brakuje tylko pól minimum dla DL — arkusz (albo „Dlaczego” w rekrutacji bez
 * pytań) jest. Strzałka otwiera wtedy małe okno z tymi polami zamiast
 * „Przesuń dalej” (21.10.2026).
 */
export function minimumOnlyGap(item: Pick<KanbanItem, "screening_done" | "minimum_missing">): boolean {
  return item.screening_done !== false && (item.minimum_missing?.length ?? 0) > 0;
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
  return cardShortName(full);
}

/** Kolumny, w których nikt jeszcze nie zweryfikował osoby. */
const BEFORE_VERIFIED_COLUMNS: ReadonlySet<BoardColumnKey> = new Set(["new", "screening"]);

export interface CardOwner {
  /** Pełne imię i nazwisko; `null` = brak zapisanej osoby. */
  name: string | null;
  role: "verified" | "added";
}

/**
 * Czyja jest karta na Tablicy (decyzja Artura 20.10.2026): w „Nowych”
 * i „Screeningu” osoba, która dodała do rekrutacji; od „Zweryfikowanego”
 * w prawo (i w „Zamkniętych”) osoba, która zweryfikowała. Rekruterka
 * weryfikowała osobę dodaną przez kogoś innego, a karta dalej pokazywała
 * dodającego. Filtr „Kto dodał” i kolejka panelu liczą po dodającym (D5).
 */
export function cardOwner(
  item: Pick<KanbanItem, "added_to_job_by_name" | "verified_by_name">,
  column: BoardColumnKey | null
): CardOwner {
  const verifier = item.verified_by_name?.trim();
  if (verifier && column != null && !BEFORE_VERIFIED_COLUMNS.has(column)) {
    return { name: verifier, role: "verified" };
  }
  return { name: item.added_to_job_by_name?.trim() || null, role: "added" };
}

/**
 * Krótka nazwa osoby na karcie: pierwsze słowo, bez dwukropka na końcu.
 * Konta integracji nazywają się „Integracje: JJIT” — karta pokazywała
 * „Integracje:” w dwóch wierszach (04.10.2026).
 */
export function cardShortName(full: string | null | undefined): string | null {
  const first = full?.trim().split(/\s+/)[0]?.replace(/:+$/, "");
  return first ? first : null;
}

/**
 * Krótsze nazwy kroków na KARCIE Tablicy (04.10.2026): kolumna ma ok. 160 px
 * na tekst, a „Przygotuj CV do QC” obok „Twój ruch”, dni i strzałki łamało
 * się na „Przygo / CV d…”. Pełna nazwa zostaje w `title` i dla czytnika
 * ekranu; reguła „kto ma ruch” (`pipeline-next-action.ts` i lustro
 * w backendzie) się nie zmienia.
 */
const SHORT_STEP_LABEL: Record<string, string> = {
  "Przygotuj CV do QC": "CV do QC",
  "Umów interview / feedback klienta": "Umów rozmowę",
  "Przegląd CV i wysłanie do klienta": "Przegląd i wysyłka",
  "Uzupełnij arkusz screeningu": "Arkusz screeningu",
  // „Dlaczego ten kandydat” nie mieści się w wierszu karty przy 1280 px
  // (ucinało do „Dlacze… ten…”) — pole stoi w sekcji „Ocena” formularza.
  [WHY_CANDIDATE_LABEL]: "Wpisz ocenę",
  "Zweryfikuj i przenieś dalej": "Zweryfikuj",
  "Reakcja kandydata na ofertę": "Reakcja na ofertę",
  // Cykl rozmowy u klienta (05.10.2026).
  "Wybierz termin rozmowy": "Wybierz termin",
  "Potwierdź termin u klienta": "Potwierdź termin",
  "Prep z kandydatem przed rozmową": "Prep z kandydatem",
  "Telefon po rozmowie i debrief": "Telefon i debrief",
  "Czekamy na decyzję klienta": "Decyzja klienta",
};

/** „Rozmowa 08.10 — prep z kandydatem” → „Prep · rozmowa 08.10”. */
const PREP_BEFORE_INTERVIEW = /^Rozmowa (\d{2}\.\d{2}) — prep z kandydatem$/;

export function shortStepLabel(label: string): string {
  const prep = PREP_BEFORE_INTERVIEW.exec(label);
  if (prep) return `Prep · rozmowa ${prep[1]}`;
  return SHORT_STEP_LABEL[label] ?? label;
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
    /** Przegląd przed wysłaniem do klienta należy do patrzącego (serwer). */
    viewerOwnsDlReview?: boolean;
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
    if (ctx.stageBadge === "cpro") {
      return { who: "Osoba od Cpro", mine: false, label: "Wrzuć CV do Cpro" };
    }
    // U Nordei Delivery Lead akceptuje osobę do kolejki Cpro (13.10.2026).
    const label = ctx.cproEnabled
      ? "Przegląd CV i akceptacja do Cpro"
      : "Przegląd CV i wysłanie do klienta";
    // Delivery Lead tej rekrutacji widzi swój ruch jak rekruter swój; pozostali
    // (także DL innej rekrutacji i admin) — „DL”.
    if (ctx.viewerOwnsDlReview && countsForDlReview(item, ctx.column, false)) {
      return { who: MY_MOVE_LABEL, mine: true, label };
    }
    return { who: "DL", mine: false, label };
  }
  if (action.kind === "none" || action.owner === "none" || !action.label) return null;
  const role = ROLE_WHO[action.owner];
  if (role) return { who: role, mine: false, label: action.label };
  return { ...recruiterSideWho(item, action.owner, ctx.viewerId), label: action.label };
}
