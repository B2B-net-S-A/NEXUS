"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Check, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { RejectionWorkModeField } from "@/components/v2/modals/RejectionWorkModeField";
import { useJobPipelineTemplate } from "@/hooks/useJobPipelineTemplate";
import { usePipelineMoveCore } from "@/hooks/usePipelineMoveCore";
import type {
  ReviewBatchItem,
  ReviewBatchRoleProfile,
  ReviewBatchClientRecent,
  ReviewBatchSentBefore,
} from "@/lib/api/reviewBatch";
import {
  autofillMoveFields,
  autofillReasonLabel,
  CLEANUP_KIND_LABEL,
  GAP_KIND_LABEL,
  gapsNote,
  notLookingUntil,
  NOT_LOOKING_DEFAULT_MONTHS,
  otherNoteHasWords,
  ROLE_KIND_CHOICES,
  ROLE_KIND_LABEL,
  templateReasonFor,
  type AutofillAvailability,
  type AutofillCleanupKind,
  type AutofillDetail,
  type AutofillGap,
  type AutofillGapKind,
  type AutofillLearnedFrom,
  type AutofillReason,
  type AutofillRoleKind,
} from "@/lib/autofill-feedback";
import { warsawToday } from "@/lib/warsaw-date";
import { daysAgoText, knownFactLabels } from "@/lib/new-column-queue";
import { closeReason } from "@/lib/close-reasons";
import { reasonNeedsDescription, WORK_MODE_MISMATCH_REASON } from "@/lib/rejection-reasons";
import { cn } from "@/lib/utils";

import { hasKeyFacts, ReviewBatchKeyFactsBlock } from "./ReviewBatchKeyFacts";
import { hasRequirementSteps, ReviewBatchRequirementsBlock } from "./ReviewBatchRequirements";

/**
 * Jedna osoba z porcji dnia (makieta M7, decyzje Artura z 07.11.2026): wszystko
 * do decyzji na jednym widoku, decyzja jednym klawiszem, bez pomijania.
 * Ruch idzie przez `usePipelineMoveCore` — ta sama droga co Tablica.
 */

/**
 * Powody pod klawiszami 1–9 i 0. Od 12.11.2026 (raport z 323 odrzuceń porcji):
 * „Język” rozdzielony na polski i angielski (19 z 20 opisów to było samo
 * „Język”), „Forma umowy” zamiast „Inne” (3 takie opisy).
 */
/**
 * Powody pod klawiszami 0–9. Od 19.11.2026 nazwy z jednego słownika powodów
 * (`lib/close-reasons.ts`) — te same co w oknie „Zamknij proces”, żeby ten
 * sam klucz nie miał w porcji innej nazwy niż na Tablicy.
 */
const QUICK_KEYS: { key: string; value: AutofillReason }[] = [
  { key: "1", value: "missing_skill" },
  { key: "2", value: "too_junior" },
  { key: "3", value: "location_mode" },
  { key: "4", value: "too_expensive" },
  { key: "5", value: "no_polish" },
  { key: "6", value: "weak_english" },
  { key: "7", value: "other_level_or_role" },
  { key: "8", value: "not_looking" },
  { key: "9", value: "contract_form" },
  { key: "0", value: "other" },
];
export const QUICK_REASONS: { key: string; value: AutofillReason; label: string }[] = QUICK_KEYS.map(
  (r) => ({ ...r, label: closeReason(r.value)?.label ?? r.value }),
);

/** Najwyżej tyle pozycji wymagań pod „Brak umiejętności”: najpierw te, których system nie znalazł. */
export const GAP_ROWS = 8;
const GAP_KINDS: AutofillGapKind[] = ["missing", "mention", "too_few_years"];

export function gapRows(item: Pick<ReviewBatchItem, "matched_must" | "missing_must">): string[] {
  const seen = new Set<string>();
  const rows: string[] = [];
  for (const label of [...item.missing_must, ...item.matched_must]) {
    const key = label.trim().toLowerCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    rows.push(label.trim());
    if (rows.length === GAP_ROWS) break;
  }
  return rows;
}

/**
 * Szczegóły powodu w porcji (16.11.2026, feedback z 13.11): „Inna rola” mówi,
 * co nie pasuje (49 odrzuceń bez słowa), „Nie szuka” zapisuje wypowiedzenie
 * albo datę, „Za drogi” kwotę, a porządki tablicy nie uczą systemu.
 */
export interface RejectExtras {
  cleanup?: AutofillCleanupKind | null;
  availability?: AutofillAvailability;
  availableFrom?: string;
}

/** Okres wypowiedzenia do wyboru (miesiące). */
export const NOTICE_MONTHS = [1, 2, 3] as const;

export const AVAILABILITY_LABEL: Record<AutofillAvailability, string> = {
  not_looking: `Nie szuka (wraca za ${NOT_LOOKING_DEFAULT_MONTHS} mies.)`,
  notice: "Okres wypowiedzenia",
  from_date: "Dostępny od…",
};

/** Czego brakuje do wysłania odrzucenia (pusty tekst = gotowe). */
export function rejectMissing(
  reason: AutofillReason | null,
  note: string,
  gapCount = 0,
  extras: RejectExtras = {},
): string {
  if (!reason) return "Wybierz powód (1–9, 0).";
  if (reason === "missing_skill" && gapCount === 0 && !note.trim()) {
    return "Kliknij, czego brakuje, albo wpisz coś spoza listy.";
  }
  if (reason === "other" && !extras.cleanup && !otherNoteHasWords(note)) {
    return "Opisz powód słowami albo wybierz porządki.";
  }
  if (reason === "not_looking" && extras.availability === "from_date") {
    if (!extras.availableFrom) return "Podaj, od kiedy jest dostępny.";
    if (extras.availableFrom < tomorrowIso()) return "Data dostępności musi być w przyszłości.";
  }
  return "";
}

/** Jutro w kalendarzu firmy („RRRR-MM-DD”). */
export function tomorrowIso(today: string = warsawToday()): string {
  const [y, m, d] = today.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + 1)).toISOString().slice(0, 10);
}

/** Powód dla serwera: „Inne” z wybranymi porządkami to `cleanup`. */
export function effectiveReason(reason: AutofillReason, cleanup: AutofillCleanupKind | null): AutofillReason {
  return reason === "other" && cleanup ? "cleanup" : reason;
}

/** „Nie szuka do” dla wybranej dostępności. */
export function availabilityUntil(
  availability: AutofillAvailability,
  noticeMonths: number,
  availableFrom: string,
): string | null {
  if (availability === "notice") return notLookingUntil(noticeMonths);
  if (availability === "from_date") return availableFrom || null;
  return notLookingUntil(NOT_LOOKING_DEFAULT_MONTHS);
}

/** Szczegół powodu do `autofill_detail`; `null`, gdy nic nie wybrano. */
export function rejectDetail(
  reason: AutofillReason,
  roleKind: AutofillRoleKind | null,
  roleWanted: string,
  availability: AutofillAvailability,
  cleanup: AutofillCleanupKind | null,
  personRole = "",
): AutofillDetail | null {
  if (reason === "other_level_or_role") {
    const detail: AutofillDetail = {};
    if (roleKind) detail.role_kind = roleKind;
    if (roleWanted.trim()) detail.role_wanted = roleWanted.trim();
    if (personRole.trim()) detail.person_role = personRole.trim();
    return Object.keys(detail).length ? detail : null;
  }
  if (reason === "not_looking") return { availability };
  if (reason === "other" && cleanup) return { cleanup };
  return null;
}

/** Opis do historii procesu: to, co rekruter kliknął, słowami. */
export function historyNote(
  reason: AutofillReason,
  note: string,
  roleKind: AutofillRoleKind | null,
  roleWanted: string,
  cleanup: AutofillCleanupKind | null,
  personRole = "",
): string {
  if (reason === "other_level_or_role") {
    return [
      roleKind ? ROLE_KIND_LABEL[roleKind] : null,
      personRole.trim() ? `osoba: ${personRole.trim()}` : null,
      roleWanted.trim() ? `szukamy: ${roleWanted.trim()}` : null,
    ]
      .filter(Boolean)
      .join(", ");
  }
  if (reason === "other" && cleanup) return [CLEANUP_KIND_LABEL[cleanup], note.trim()].filter(Boolean).join(". ");
  return note;
}

function roleKey(label: string): string {
  return label.split(/\s+/).filter(Boolean).join(" ").toLocaleLowerCase("pl");
}

/**
 * „Silnik zapamięta: …” pod „Osoba to:” (16.11.2026): ile razy ta etykieta
 * już padła w tej rekrutacji i że od progu (`exclude_min`, 3) silnik przestaje
 * dokładać osoby z takim stanowiskiem. `null`, gdy pole jest puste.
 */
export function rememberLine(personRole: string, profile?: ReviewBatchRoleProfile | null): string | null {
  const label = personRole.trim();
  const key = roleKey(label);
  if (!key) return null;
  if (profile?.excluded.some((e) => roleKey(e.label) === key)) {
    return `„${label}” już jest w „Nie proponujemy”: silnik nie dokłada takich osób do tej rekrutacji.`;
  }
  const learning = profile?.learning.find((l) => roleKey(l.label) === key);
  const next = (learning?.count ?? 0) + 1;
  if (learning?.dismissed) {
    return `Silnik zapamięta: „${label}” po raz ${next}. Ktoś zdjął to z „Nie proponujemy”, więc dalej będzie proponować.`;
  }
  const min = profile?.exclude_min ?? 3;
  return next >= min
    ? `Silnik zapamięta: „${label}” po raz ${next}. Od teraz nie proponuje takich osób w tej rekrutacji.`
    : `Silnik zapamięta: „${label}” po raz ${next}. Od ${min}. razu przestaje proponować takie osoby w tej rekrutacji.`;
}

/** „Ile chce?” — dodatnia liczba zł/h albo `null`. */
export function parseAskedRate(value: string): number | null {
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) && n > 0 && n <= 10000 ? n : null;
}

/**
 * Powód z szablonu i opis dla `/api/pipeline/move` (09.11.2026): klawisze 3 i 5
 * kończyły się 422. „Nie akceptuje trybu pracy” wymaga dni w biurze, a przy
 * „Lokalizacji / trybie” z profilu ich nie znamy, więc bez dni idzie „Inne”:
 * domyślne „Tylko zdalnie” zapisałoby na profilu nieprawdę. „Inne” bez opisu
 * serwer odrzuca, więc opisem jest nazwa powodu, jak w oknie odrzucenia.
 */
function templateMoveFields<T extends { id: string; name?: string; label: string }>(
  reason: AutofillReason,
  note: string,
  officeDays: number | null,
  saveWorkMode: boolean,
  templates: T[],
  gaps: readonly AutofillGap[] = [],
) {
  const template = templateReasonFor(
    reason === "location_mode" && officeDays === null ? "other" : reason,
    templates,
  );
  const written = reason === "missing_skill" ? gapsNote(gaps, note) : note.trim();
  const labelled =
    reason !== "missing_skill" && reason !== "other" && reasonNeedsDescription(template);
  return {
    rejection_reason_id: template?.id || undefined,
    notes: (labelled ? [autofillReasonLabel(reason), written].filter(Boolean).join(". ") : written) || undefined,
    ...(template?.name?.trim() === WORK_MODE_MISMATCH_REASON && officeDays !== null
      ? { work_mode_max_onsite_days: officeDays, work_mode_save_to_profile: saveWorkMode }
      : {}),
  };
}

/** Dlaczego osoba stoi na tym miejscu; `null`, gdy decyduje sam wynik. */
export function orderLine(item: ReviewBatchItem): string | null {
  const parts = [
    ...knownFactLabels(item.known).map((label) => label.toLowerCase()),
    item.order_active ? "aktywnie szuka" : null,
    item.order_in_budget ? "stawka w budżecie" : null,
  ].filter(Boolean);
  const later = [
    item.order_polish_later ? "polski nie ojczysty" : null,
    item.order_leader_gap ? "szukamy lidera" : null,
  ].filter(Boolean);
  const laterText = later.length ? ` · ${later.join(", ")} → dalej` : "";
  // Schodki (23.11.2026): liczba spełnionych „musi mieć” decyduje przed wynikiem.
  const req = item.requirements;
  const steps = req && req.must_total > 0 ? `${req.must_met} z ${req.must_total} musi mieć · ` : "";
  if (!parts.length) {
    return laterText || steps ? `Kolejność: ${steps}${Math.round(item.score)}%${laterText}` : null;
  }
  return `Kolejność: ${steps}${Math.round(item.score)}% + ${parts.join(" + ")}${laterText}`;
}

/** „Wysłany do klienta 2× · ostatnio 7 dni temu: …” (Z1, 20.11.2026). */
export function sentBeforeText(sent: ReviewBatchSentBefore): string {
  const when = sent.last_days <= 0 ? "dziś" : sent.last_days === 1 ? "wczoraj" : `${sent.last_days} dni temu`;
  const title = sent.last_job_title.trim();
  return `Wysłany do klienta ${sent.count}× · ostatnio ${when}${title ? `: ${title}` : ""}`;
}

/** „Wysłany wczoraj do tego klienta: Java Developer. Klient zna już to CV.” (R4) */
export function clientRecentText(recent: ReviewBatchClientRecent): string {
  const when = recent.days == null ? "niedawno" : daysAgoText(recent.days);
  const title = recent.job_title.trim();
  return `Wysłany ${when} do tego klienta${title ? `: ${title}` : ""}. Klient zna już to CV.`;
}

function ClientRecentLine({ recent }: { recent: ReviewBatchClientRecent }) {
  const text = clientRecentText(recent);
  return (
    <p
      className="rounded-md bg-primary/10 px-2.5 py-1.5 text-xs font-medium text-primary"
      title={text}
      data-testid="review-client-recent"
      data-tour="review-batch.client-recent"
    >
      {text}
    </p>
  );
}

function SentBeforeLine({ sent }: { sent: ReviewBatchSentBefore }) {
  const text = sentBeforeText(sent);
  return (
    <p
      className="truncate rounded-md border border-success/40 bg-success/10 px-2.5 py-1.5 text-xs text-success"
      title={text}
      data-testid="review-sent-before"
    >
      {text}
    </p>
  );
}

function rateLine(item: ReviewBatchItem): string | null {
  if (item.rate_from_hourly == null) return null;
  const rate = `od ${Math.round(item.rate_from_hourly)} ${item.rate_currency === "PLN" || !item.rate_currency ? "zł" : item.rate_currency}/h`;
  return item.budget_hourly != null ? `${rate} · budżet ${Math.round(item.budget_hourly)}` : rate;
}

export function ReviewBatchCard({
  item,
  onDecided,
  hideJob = false,
  onPickRequirement,
  profile = null,
}: {
  item: ReviewBatchItem;
  onDecided: () => void;
  hideJob?: boolean;
  /** Profil „Kogo szukamy” rekrutacji: podpowiedź „Szukamy:” i licznik „Nie proponujemy”. */
  profile?: ReviewBatchRoleProfile | null;
  /** Klik w pozycję „Kluczowe”: CV po prawej szuka tej frazy. */
  onPickRequirement?: (label: string) => void;
}) {
  const move = usePipelineMoveCore({ jobId: item.job_id });
  const { rejectionReasons } = useJobPipelineTemplate(item.job_id);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState<AutofillReason | null>(null);
  const [learnedFrom, setLearnedFrom] = useState<AutofillLearnedFrom>("profile");
  const [note, setNote] = useState("");
  const [gapKinds, setGapKinds] = useState<Record<string, AutofillGapKind>>({});
  /** `null` — rekruter nie zna dni w biurze (domyślnie). */
  const [officeDays, setOfficeDays] = useState<number | null>(null);
  const [saveWorkMode, setSaveWorkMode] = useState(true);
  const [busy, setBusy] = useState(false);
  const [roleKind, setRoleKind] = useState<AutofillRoleKind | null>(null);
  const [roleWanted, setRoleWanted] = useState(profile?.role ?? "");
  const [personRole, setPersonRole] = useState(item.position ?? "");
  const [askedRate, setAskedRate] = useState("");
  const [availability, setAvailability] = useState<AutofillAvailability>("not_looking");
  const [noticeMonths, setNoticeMonths] = useState<number>(3);
  const [availableFrom, setAvailableFrom] = useState("");
  const [cleanup, setCleanup] = useState<AutofillCleanupKind | null>(null);

  const rows = useMemo(() => gapRows(item), [item]);
  const gaps = useMemo<AutofillGap[]>(
    () => rows.filter((label) => gapKinds[label]).map((label) => ({ label, kind: gapKinds[label] })),
    [rows, gapKinds],
  );
  const missing = useMemo(
    () => rejectMissing(reason, note, gaps.length, { cleanup, availability, availableFrom }),
    [reason, note, gaps.length, cleanup, availability, availableFrom],
  );
  const templates = useMemo(
    () => rejectionReasons.filter((r) => r.applies_to?.includes("rejected")),
    [rejectionReasons],
  );
  const canAskOfficeDays =
    reason === "location_mode" &&
    templates.some((r) => r.name?.trim() === WORK_MODE_MISMATCH_REASON);
  const rate = rateLine(item);
  const order = orderLine(item);
  const remember = reason === "other_level_or_role" ? rememberLine(personRole, profile) : null;
  const overBudget =
    item.rate_from_hourly != null &&
    item.budget_hourly != null &&
    item.rate_from_hourly > item.budget_hourly;

  const toScreening = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    const outcome = await move.send(
      { candidate_id: item.candidate_id, job_id: item.job_id, stage: "screening" },
      { candidateName: item.name },
    );
    setBusy(false);
    if (outcome.ok) onDecided();
  }, [busy, move, item, onDecided]);

  const reject = useCallback(async () => {
    if (busy || missing || !reason) return;
    setBusy(true);
    const sent = effectiveReason(reason, cleanup);
    const outcome = await move.send(
      {
        candidate_id: item.candidate_id,
        job_id: item.job_id,
        stage: "rejected",
        send_rejection_email: false,
        ...templateMoveFields(
          sent,
          historyNote(reason, note, roleKind, roleWanted, cleanup, personRole),
          officeDays,
          saveWorkMode,
          templates,
          gaps,
        ),
        ...autofillMoveFields({
          reason: sent,
          learnedFrom,
          rateHourly: reason === "too_expensive" ? parseAskedRate(askedRate) : null,
          notLookingUntil:
            reason === "not_looking" ? availabilityUntil(availability, noticeMonths, availableFrom) : null,
          gaps,
          detail: rejectDetail(reason, roleKind, roleWanted, availability, cleanup, personRole),
        }),
      },
      { candidateName: item.name },
    );
    setBusy(false);
    if (outcome.ok) onDecided();
  }, [
    busy,
    missing,
    reason,
    templates,
    move,
    item,
    note,
    officeDays,
    saveWorkMode,
    learnedFrom,
    gaps,
    cleanup,
    roleKind,
    roleWanted,
    personRole,
    askedRate,
    availability,
    noticeMonths,
    availableFrom,
    onDecided,
  ]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      // Okno „Kogo szukamy” nad kartą ma własne pola i przyciski.
      if (target?.closest?.('[role="dialog"]')) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const key = event.key.toLowerCase();
      if (!rejecting && key === "s") {
        event.preventDefault();
        void toScreening();
      } else if (!rejecting && key === "o") {
        event.preventDefault();
        setRejecting(true);
      } else if (rejecting) {
        // Po „7 Inna rola” klawisze 1–8 wybierają, co nie gra z rolą;
        // Backspace wraca do wyboru powodu.
        const roleChoice =
          reason === "other_level_or_role" && /^[1-8]$/.test(key) ? ROLE_KIND_CHOICES[Number(key) - 1] : null;
        const quick = QUICK_REASONS.find((r) => r.key === key);
        if (roleChoice) {
          event.preventDefault();
          setRoleKind((current) => (current === roleChoice ? null : roleChoice));
        } else if (reason === "other_level_or_role" && key === "backspace") {
          event.preventDefault();
          setReason(null);
          setRoleKind(null);
        } else if (quick) {
          event.preventDefault();
          setReason(quick.value);
        } else if (key === "r") {
          setLearnedFrom((v) => (v === "profile" ? "call" : "profile"));
        } else if (key === "escape") {
          setRejecting(false);
        } else if (key === "enter") {
          event.preventDefault();
          void reject();
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rejecting, reason, toScreening, reject]);

  return (
    <div className="space-y-3" data-testid="review-batch-card">
      <div className="rounded-lg border border-border bg-card p-4 space-y-3">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            {hideJob ? null : (
              <div className="text-xs text-muted-foreground truncate">
                {item.job_title} · {item.job_id}
              </div>
            )}
            <h2 className="text-lg font-semibold leading-tight">
              <Link
                href={`/candidates/${item.candidate_id}`}
                target="_blank"
                className="hover:underline"
              >
                {item.name}
              </Link>
            </h2>
            <div className="text-sm text-muted-foreground">
              {[item.position, item.years != null ? `${item.years} lat` : null, item.city]
                .filter(Boolean)
                .join(" · ") || "Brak roli, lat i miasta w profilu"}
            </div>
          </div>
          <div
            className="shrink-0 rounded-full border-2 border-primary px-2 py-1 text-sm font-bold text-primary tabular-nums"
            aria-label={`Dopasowanie ${Math.round(item.score)}%`}
          >
            {Math.round(item.score)}%
          </div>
        </div>
        {item.client_recent ? <ClientRecentLine recent={item.client_recent} /> : null}
        {item.sent_before ? <SentBeforeLine sent={item.sent_before} /> : null}
        {order ? <p className="text-xs text-muted-foreground">{order}</p> : null}
        {hasKeyFacts(item.key_facts) ? (
          // Lekcja „Porcja: kolejność po spełnionych »musi mieć«” każe kliknąć wymaganie
          // na karcie. W kolejkach z 25.11.2026 żadna karta (0 z 53) nie miała listy
          // ze schodkami, wszystkie — „Kluczowe” z tym samym klikiem do CV.
          <div data-tour={hasRequirementSteps(item.requirements) ? undefined : "review-batch.requirements"}>
            <ReviewBatchKeyFactsBlock
              facts={item.key_facts}
              restMatched={hasRequirementSteps(item.requirements) ? 0 : item.matched_must.length}
              restTotal={
                hasRequirementSteps(item.requirements) ? 0 : item.matched_must.length + item.missing_must.length
              }
              onPick={onPickRequirement}
            />
          </div>
        ) : null}
        {hasRequirementSteps(item.requirements) ? (
          <ReviewBatchRequirementsBlock requirements={item.requirements} onPick={onPickRequirement} />
        ) : hasKeyFacts(item.key_facts) ? null : (
        <div className="flex flex-wrap gap-1.5" aria-label="Musi mieć">
          {item.matched_must.map((m) => (
            <span key={`m-${m}`} className="rounded bg-success/15 px-1.5 py-0.5 text-xs text-success">
              ✓ {m}
            </span>
          ))}
          {item.missing_must.map((m) => (
            <span key={`x-${m}`} className="rounded bg-warning/15 px-1.5 py-0.5 text-xs text-warning">
              ? {m}
            </span>
          ))}
        </div>
        )}
        <div className="flex flex-wrap gap-1.5 text-xs">
          {item.availability_status === "actively_looking" ? (
            <span className="rounded bg-primary/10 px-1.5 py-0.5 text-primary">Aktywnie szuka</span>
          ) : null}
          {rate ? (
            <span
              className={cn(
                "rounded px-1.5 py-0.5",
                overBudget ? "bg-warning/15 text-warning" : "bg-success/15 text-success",
              )}
            >
              {rate}
            </span>
          ) : (
            <span className="rounded bg-muted px-1.5 py-0.5 text-muted-foreground">stawka nieznana</span>
          )}
          {item.cautions.map((c) => (
            <span key={c.key} title={c.title} className="rounded bg-warning/15 px-1.5 py-0.5 text-warning">
              {c.label}
            </span>
          ))}
        </div>
      </div>

      {!rejecting ? (
        <>
        <div className="flex flex-wrap gap-2">
          <Button
            onClick={() => void toScreening()}
            disabled={busy}
            data-testid="review-to-screening"
            data-tour="review-batch.to-screening"
          >
            <Check className="h-4 w-4" aria-hidden="true" /> Pasuje <kbd className="ml-1 text-xs opacity-70">S</kbd>
          </Button>
          <Button
            variant="outline"
            onClick={() => setRejecting(true)}
            disabled={busy}
            data-testid="review-reject"
            data-tour="review-batch.reject"
          >
            <X className="h-4 w-4" aria-hidden="true" /> Nie pasuje… <kbd className="ml-1 text-xs opacity-70">O</kbd>
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          „Pasuje” (osoba idzie do screeningu) i „Nie pasuje” z powodem liczą się od razu. Wynik screeningu wpisz w 2 dni robocze, inaczej wyszukiwanie znów się zablokuje.
        </p>
        </>
      ) : (
        <div className="rounded-lg border border-border bg-card p-3 space-y-3" data-testid="review-reject-form">
          <div className="text-sm font-medium">Dlaczego odrzucasz? (1–9, 0)</div>
          <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Powód odrzucenia">
            {QUICK_REASONS.map((r) => (
              <button
                key={r.value}
                type="button"
                role="radio"
                aria-checked={reason === r.value}
                onClick={() => setReason(r.value)}
                className={cn(
                  "rounded-md border px-2 py-1 text-xs",
                  reason === r.value
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border hover:bg-muted",
                )}
              >
                {r.key} {r.label}
              </button>
            ))}
          </div>
          {reason === "missing_skill" && rows.length > 0 ? (
            <div className="space-y-1" data-testid="review-reject-gaps">
              <div className="text-xs text-muted-foreground">Czego brakuje? Kliknij przy pozycji:</div>
              {rows.map((label) => (
                <div key={label} className="flex flex-wrap items-center gap-1 text-xs">
                  <span className="w-28 truncate font-medium" title={label}>
                    {label}
                  </span>
                  {GAP_KINDS.map((kind) => {
                    const on = gapKinds[label] === kind;
                    return (
                      <button
                        key={kind}
                        type="button"
                        aria-pressed={on}
                        aria-label={`${label}: ${GAP_KIND_LABEL[kind]}`}
                        onClick={() =>
                          setGapKinds((current) => {
                            const next = { ...current };
                            if (on) delete next[label];
                            else next[label] = kind;
                            return next;
                          })
                        }
                        className={cn(
                          "rounded border px-1.5 py-0.5",
                          on ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-muted",
                        )}
                      >
                        {GAP_KIND_LABEL[kind]}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          ) : null}
          {reason === "other_level_or_role" ? (
            <div className="space-y-1.5" data-testid="review-reject-role">
              <div className="text-xs text-muted-foreground">
                Co nie gra z rolą? (1–8, opcjonalnie; Backspace: inny powód)
              </div>
              <div className="flex flex-wrap gap-1 text-xs" role="group" aria-label="Co nie gra z rolą">
                {ROLE_KIND_CHOICES.map((kind, index) => (
                  <button
                    key={kind}
                    type="button"
                    aria-pressed={roleKind === kind}
                    aria-label={ROLE_KIND_LABEL[kind]}
                    onClick={() => setRoleKind(roleKind === kind ? null : kind)}
                    className={cn(
                      "rounded border px-1.5 py-0.5",
                      roleKind === kind ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-muted",
                    )}
                  >
                    <span className="tabular-nums opacity-70">{index + 1}</span> {ROLE_KIND_LABEL[kind]}
                  </button>
                ))}
              </div>
              <div className="grid grid-cols-[auto_1fr] items-center gap-x-2 gap-y-1 text-xs">
                <label htmlFor="review-reject-person-role" className="text-muted-foreground">
                  Osoba to:
                </label>
                <input
                  id="review-reject-person-role"
                  value={personRole}
                  maxLength={120}
                  onChange={(e) => setPersonRole(e.target.value)}
                  className="w-full rounded border border-border bg-background px-2 py-1"
                  placeholder="np. Oracle DBA, tester manualny"
                />
                <label htmlFor="review-reject-role-wanted" className="text-muted-foreground">
                  Szukamy:
                </label>
                <input
                  id="review-reject-role-wanted"
                  value={roleWanted}
                  maxLength={120}
                  onChange={(e) => setRoleWanted(e.target.value)}
                  className="w-full rounded border border-border bg-background px-2 py-1"
                  placeholder="np. analityk biznesowy (opcjonalnie)"
                />
              </div>
              {remember ? (
                <p className="text-xs text-muted-foreground" data-testid="review-reject-remember">
                  {remember}
                </p>
              ) : null}
            </div>
          ) : null}
          {reason === "too_expensive" ? (
            <div className="space-y-1 text-xs" data-testid="review-reject-rate">
              <div className="flex items-center gap-2">
                <label htmlFor="review-reject-rate" className="text-muted-foreground">
                  Ile chce?
                </label>
                <input
                  id="review-reject-rate"
                  value={askedRate}
                  onChange={(e) => setAskedRate(e.target.value.replace(/[^\d]/g, "").slice(0, 5))}
                  inputMode="numeric"
                  className="w-20 rounded border border-border bg-background px-2 py-1 tabular-nums"
                  placeholder="np. 140"
                />
                <span className="text-muted-foreground">
                  zł/h{item.budget_hourly != null ? ` · budżet ${Math.round(item.budget_hourly)}` : ""}
                </span>
              </div>
              <p className="text-muted-foreground">
                Opcjonalnie. Kwota trafi na profil jako „Stawka od”, więc system przestanie proponować tę osobę do niższych budżetów.
              </p>
            </div>
          ) : null}
          {reason === "not_looking" ? (
            <div className="flex flex-wrap items-center gap-1 text-xs" data-testid="review-reject-availability">
              {(Object.keys(AVAILABILITY_LABEL) as AutofillAvailability[]).map((kind) => (
                <button
                  key={kind}
                  type="button"
                  aria-pressed={availability === kind}
                  onClick={() => setAvailability(kind)}
                  className={cn(
                    "rounded border px-1.5 py-0.5",
                    availability === kind ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-muted",
                  )}
                >
                  {AVAILABILITY_LABEL[kind]}
                </button>
              ))}
              {availability === "notice" ? (
                <select
                  id="review-reject-notice"
                  aria-label="Okres wypowiedzenia"
                  value={noticeMonths}
                  onChange={(e) => setNoticeMonths(Number(e.target.value))}
                  className="rounded border border-border bg-background px-1 py-0.5"
                >
                  {NOTICE_MONTHS.map((m) => (
                    <option key={m} value={m}>
                      {m} mies.
                    </option>
                  ))}
                </select>
              ) : null}
              {availability === "from_date" ? (
                <input
                  id="review-reject-available-from"
                  aria-label="Dostępny od"
                  type="date"
                  min={tomorrowIso()}
                  max={notLookingUntil(24)}
                  value={availableFrom}
                  onChange={(e) => setAvailableFrom(e.target.value)}
                  className="rounded border border-border bg-background px-1 py-0.5"
                />
              ) : null}
            </div>
          ) : null}
          {reason === "other" ? (
            <div className="flex flex-wrap items-center gap-1 text-xs" data-testid="review-reject-cleanup">
              <span className="text-muted-foreground">Nie ocena osoby (system się z tego nie uczy):</span>
              {(Object.keys(CLEANUP_KIND_LABEL) as AutofillCleanupKind[]).map((kind) => (
                <button
                  key={kind}
                  type="button"
                  aria-pressed={cleanup === kind}
                  onClick={() => setCleanup(cleanup === kind ? null : kind)}
                  className={cn(
                    "rounded border px-1.5 py-0.5",
                    cleanup === kind ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-muted",
                  )}
                >
                  {CLEANUP_KIND_LABEL[kind]}
                </button>
              ))}
            </div>
          ) : null}
          {reason === "missing_skill" || reason === "other" ? (
            <Textarea
              id="review-reject-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              placeholder={
                reason === "missing_skill"
                  ? "Coś spoza listy, np. produkty inwestycyjne (opcjonalnie)"
                  : cleanup
                    ? "Dodatkowy opis (opcjonalnie)"
                    : "Opisz powód"
              }
            />
          ) : null}
          {canAskOfficeDays ? (
            <button
              type="button"
              aria-pressed={officeDays !== null}
              onClick={() => setOfficeDays((days) => (days === null ? 0 : null))}
              className={cn(
                "rounded border px-1.5 py-0.5 text-xs",
                officeDays !== null ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-muted",
              )}
            >
              Znam liczbę dni w biurze, które akceptuje
            </button>
          ) : null}
          {canAskOfficeDays && officeDays !== null ? (
            <RejectionWorkModeField
              job={null}
              several={false}
              days={officeDays}
              onDaysChange={setOfficeDays}
              saveToProfile={saveWorkMode}
              onSaveToProfileChange={setSaveWorkMode}
              inset={false}
            />
          ) : null}
          <div className="flex items-center gap-2 text-xs">
            <span className="text-muted-foreground">Skąd wiesz (R):</span>
            {(["profile", "call"] as const).map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => setLearnedFrom(v)}
                aria-pressed={learnedFrom === v}
                className={cn(
                  "rounded border px-1.5 py-0.5",
                  learnedFrom === v ? "border-primary bg-primary/10 text-primary" : "border-border",
                )}
              >
                {v === "profile" ? "z profilu" : "po rozmowie"}
              </button>
            ))}
          </div>
          {missing ? <p className="text-xs text-muted-foreground">{missing}</p> : null}
          <div className="flex gap-2">
            <Button onClick={() => void reject()} disabled={busy || Boolean(missing)} data-testid="review-reject-confirm">
              Odrzuć <kbd className="ml-1 text-xs opacity-70">Enter</kbd>
            </Button>
            <Button variant="ghost" onClick={() => setRejecting(false)} disabled={busy}>
              Wróć <kbd className="ml-1 text-xs opacity-70">Esc</kbd>
            </Button>
          </div>
        </div>
      )}
      {move.dialogs}
    </div>
  );
}
