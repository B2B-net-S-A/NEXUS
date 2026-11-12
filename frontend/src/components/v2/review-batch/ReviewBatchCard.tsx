"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Check, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { RejectionWorkModeField } from "@/components/v2/modals/RejectionWorkModeField";
import { useJobPipelineTemplate } from "@/hooks/useJobPipelineTemplate";
import { usePipelineMoveCore } from "@/hooks/usePipelineMoveCore";
import type { ReviewBatchItem } from "@/lib/api/reviewBatch";
import {
  autofillMoveFields,
  autofillReasonLabel,
  GAP_KIND_LABEL,
  gapsNote,
  notLookingUntil,
  NOT_LOOKING_DEFAULT_MONTHS,
  templateReasonFor,
  type AutofillGap,
  type AutofillGapKind,
  type AutofillLearnedFrom,
  type AutofillReason,
} from "@/lib/autofill-feedback";
import { knownFactLabels } from "@/lib/new-column-queue";
import { reasonNeedsDescription, WORK_MODE_MISMATCH_REASON } from "@/lib/rejection-reasons";
import { cn } from "@/lib/utils";

import { hasKeyFacts, ReviewBatchKeyFactsBlock } from "./ReviewBatchKeyFacts";

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
export const QUICK_REASONS: { key: string; value: AutofillReason; label: string }[] = [
  { key: "1", value: "missing_skill", label: "Brak umiejętności" },
  { key: "2", value: "too_junior", label: "Za junior" },
  { key: "3", value: "location_mode", label: "Lokalizacja / tryb" },
  { key: "4", value: "too_expensive", label: "Za drogi" },
  { key: "5", value: "no_polish", label: "Brak polskiego" },
  { key: "6", value: "weak_english", label: "Angielski za słaby" },
  { key: "7", value: "other_level_or_role", label: "Inna rola" },
  { key: "8", value: "not_looking", label: "Nie szuka pracy" },
  { key: "9", value: "contract_form", label: "Forma umowy" },
  { key: "0", value: "other", label: "Inne" },
];

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

/** Czego brakuje do wysłania odrzucenia (pusty tekst = gotowe). */
export function rejectMissing(reason: AutofillReason | null, note: string, gapCount = 0): string {
  if (!reason) return "Wybierz powód (1–9, 0).";
  if (reason === "missing_skill" && gapCount === 0 && !note.trim()) {
    return "Kliknij, czego brakuje, albo wpisz coś spoza listy.";
  }
  if (reason === "other" && !note.trim()) return "Opisz powód.";
  return "";
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
  return parts.length ? `Kolejność: ${Math.round(item.score)}% + ${parts.join(" + ")}` : null;
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
}: {
  item: ReviewBatchItem;
  onDecided: () => void;
  hideJob?: boolean;
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

  const rows = useMemo(() => gapRows(item), [item]);
  const gaps = useMemo<AutofillGap[]>(
    () => rows.filter((label) => gapKinds[label]).map((label) => ({ label, kind: gapKinds[label] })),
    [rows, gapKinds],
  );
  const missing = useMemo(() => rejectMissing(reason, note, gaps.length), [reason, note, gaps.length]);
  const templates = useMemo(
    () => rejectionReasons.filter((r) => r.applies_to?.includes("rejected")),
    [rejectionReasons],
  );
  const canAskOfficeDays =
    reason === "location_mode" &&
    templates.some((r) => r.name?.trim() === WORK_MODE_MISMATCH_REASON);
  const rate = rateLine(item);
  const order = orderLine(item);
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
    const outcome = await move.send(
      {
        candidate_id: item.candidate_id,
        job_id: item.job_id,
        stage: "rejected",
        send_rejection_email: false,
        ...templateMoveFields(reason, note, officeDays, saveWorkMode, templates, gaps),
        ...autofillMoveFields({
          reason,
          learnedFrom,
          rateHourly: null,
          notLookingUntil:
            reason === "not_looking" ? notLookingUntil(NOT_LOOKING_DEFAULT_MONTHS) : null,
          gaps,
        }),
      },
      { candidateName: item.name },
    );
    setBusy(false);
    if (outcome.ok) onDecided();
  }, [busy, missing, reason, templates, move, item, note, officeDays, saveWorkMode, learnedFrom, gaps, onDecided]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const key = event.key.toLowerCase();
      if (!rejecting && key === "s") {
        event.preventDefault();
        void toScreening();
      } else if (!rejecting && key === "o") {
        event.preventDefault();
        setRejecting(true);
      } else if (rejecting) {
        const quick = QUICK_REASONS.find((r) => r.key === key);
        if (quick) {
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
  }, [rejecting, toScreening, reject]);

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
        {order ? <p className="text-xs text-muted-foreground">{order}</p> : null}
        {hasKeyFacts(item.key_facts) ? (
          <ReviewBatchKeyFactsBlock
            facts={item.key_facts}
            restMatched={item.matched_must.length}
            restTotal={item.matched_must.length + item.missing_must.length}
            onPick={onPickRequirement}
          />
        ) : (
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
          {reason === "missing_skill" || reason === "other" ? (
            <Textarea
              id="review-reject-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              placeholder={
                reason === "missing_skill" ? "Coś spoza listy, np. produkty inwestycyjne (opcjonalnie)" : "Opisz powód"
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
