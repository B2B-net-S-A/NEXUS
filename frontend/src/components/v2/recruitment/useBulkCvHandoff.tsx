"use client";

/**
 * Zbiorcze „Wyślij CV do klienta" z tabeli rekrutacji: okno potwierdzenia →
 * pętla pojedynczych przekazań (`runBulkCvHandoff`) → jedno okno wyniku
 * z linkami.
 *
 * Wołania API są te same co w warsztacie „CV do klienta" (pojedyncza osoba):
 * `cv/branded` (status), `pipeline/move` z wersją procesu, `cv/share-token`
 * na etapie SPRZED ruchu, `client-rate`. Tablica jest unieważniana RAZ, po
 * całej pętli, pod OBOMA kluczami (`["kanban", "42"]` i `["kanban", 42]`).
 *
 * Stawka do klienta: pola widzi i wysyła wyłącznie rola z
 * `canWriteClientRate` — reszta nie widzi ich wcale i nigdy nie wysyła stawki.
 */

import { useCallback, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useEligibilityWarning } from "@/components/v2/jobs/useEligibilityWarning";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";
import {
  candidateStageCvApi,
  candidatesApi,
  extractErrorMsg,
  pipelineApi,
  type RateUnit,
} from "@/lib/api";
import {
  BULK_CV_NO_LINK_ADDRESS_REASON,
  runBulkCvHandoff,
  type BulkCvHandoffOutcome,
  type BulkCvHandoffPerson,
} from "@/lib/bulk-cv-handoff";
import { runCvHandoff } from "@/lib/cv-handoff";
import { isEligibilityWarning } from "@/lib/pipeline-eligibility-warning";
import { CV_SENT_STAGE, findStageColumn } from "@/lib/pipeline-flow";
import {
  expectedStateVersionOf,
  isPipelineVersionConflict,
} from "@/lib/pipeline-version-conflict";
import { RATE_UNIT_LABELS } from "@/lib/verified-rate-gate";

import { BulkCvHandoffDialog, type BulkCvHandoffRetryTarget } from "./BulkCvHandoffDialog";
import type { ProcessPersonRow } from "./types";

export const BULK_CV_DEFAULT_LINK_DAYS = 14;
export const BULK_CV_MIN_LINK_DAYS = 1;
export const BULK_CV_MAX_LINK_DAYS = 90;

const RATE_UNITS: RateUnit[] = ["hourly", "daily", "monthly"];

export interface UseBulkCvHandoffOptions {
  jobId: number;
  jobTitle?: string | null;
  columns: KanbanColumn[];
  canWriteClientRate: boolean;
}

export interface BulkCvHandoffStartOptions {
  /** Po pętli (niezależnie od wyniku) — np. wyczyszczenie zaznaczenia. */
  onHandled?: () => void;
}

export interface BulkCvHandoffControls {
  start: (rows: ProcessPersonRow[], opts?: BulkCvHandoffStartOptions) => void;
  busy: boolean;
  dialogs: ReactNode;
}

type BulkPerson = BulkCvHandoffPerson & { item: KanbanItem };

interface PendingRun {
  rows: ProcessPersonRow[];
  onHandled?: () => void;
}

/** Puste = brak stawki (`null`); tekst nie do odczytania = `undefined`. */
function parseRate(raw: string): number | null | undefined {
  const text = raw.trim();
  if (text === "") return null;
  if (!/^\d+([.,]\d+)?$/.test(text)) return undefined;
  const value = Number.parseFloat(text.replace(",", "."));
  return Number.isFinite(value) && value > 0 ? value : undefined;
}

function peopleCountLabel(count: number): string {
  if (count === 1) return "1 osoba";
  const lastTwo = count % 100;
  const last = count % 10;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return `${count} osoby`;
  return `${count} osób`;
}

export function useBulkCvHandoff({
  jobId,
  jobTitle,
  columns,
  canWriteClientRate,
}: UseBulkCvHandoffOptions): BulkCvHandoffControls {
  const queryClient = useQueryClient();
  const { showError } = useToast();
  const eligibility = useEligibilityWarning();

  const [pending, setPending] = useState<PendingRun | null>(null);
  const [days, setDays] = useState(String(BULK_CV_DEFAULT_LINK_DAYS));
  const [unit, setUnit] = useState<RateUnit>("monthly");
  const [rates, setRates] = useState<Record<number, string>>({});
  const [progress, setProgress] = useState<{
    index: number;
    total: number;
    name: string;
  } | null>(null);
  const [asking, setAsking] = useState(false);
  const [result, setResult] = useState<{ run: number; outcomes: BulkCvHandoffOutcome[] } | null>(
    null,
  );
  const runCounter = useRef(0);
  const busyRef = useRef(false);

  const cvSentColumn = findStageColumn(columns, CV_SENT_STAGE);

  const start = useCallback(
    (rows: ProcessPersonRow[], opts?: BulkCvHandoffStartOptions) => {
      if (busyRef.current || rows.length === 0) return;
      if (!cvSentColumn) {
        showError("Szablon tej rekrutacji nie ma kolumny „CV Wysłane”.");
        return;
      }
      setDays(String(BULK_CV_DEFAULT_LINK_DAYS));
      setUnit("monthly");
      setRates({});
      setPending({ rows, onHandled: opts?.onHandled });
    },
    [cvSentColumn, showError],
  );

  const numericDays = /^\d+$/.test(days.trim()) ? Number.parseInt(days.trim(), 10) : Number.NaN;
  const daysValid =
    Number.isInteger(numericDays) &&
    numericDays >= BULK_CV_MIN_LINK_DAYS &&
    numericDays <= BULK_CV_MAX_LINK_DAYS;
  const invalidRateIds = canWriteClientRate
    ? (pending?.rows ?? [])
        .filter((row) => parseRate(rates[row.candidateId] ?? "") === undefined)
        .map((row) => row.candidateId)
    : [];

  const run = async (runRows: ProcessPersonRow[], onHandled: (() => void) | undefined) => {
    if (!cvSentColumn || busyRef.current) return;
    busyRef.current = true;
    const expiresInDays = numericDays;
    const people: BulkPerson[] = runRows.map((row) => {
      const value = canWriteClientRate ? parseRate(rates[row.candidateId] ?? "") : null;
      return {
        candidateId: row.candidateId,
        fullName: row.fullName,
        // `item.id` = wiersz CandidateStage SPRZED ruchu — na nim leży CV firmowe.
        sourceStageId: row.item.id,
        clientRate: value ? { value, unit, currency: "PLN" } : null,
        item: row.item,
      };
    });
    setPending(null);
    setProgress({ index: 0, total: people.length, name: people[0]?.fullName ?? "" });

    let outcomes: BulkCvHandoffOutcome[] = [];
    try {
      outcomes = await runBulkCvHandoff<BulkPerson>(people, {
        expiresInDays,
        onProgress: (index, total, person) =>
          setProgress({ index, total, name: person.fullName }),
        getBrandedStatus: async (stageId) =>
          (await candidateStageCvApi.branded.get(stageId)).data?.status ?? "none",
        handoff: (person, acknowledgeEligibility) =>
          runCvHandoff(
            { clientRate: person.clientRate, shareLink: { expiresInDays } },
            {
              move: async () => {
                await pipelineApi.move({
                  candidate_id: person.candidateId,
                  job_id: jobId,
                  stage: CV_SENT_STAGE,
                  stage_def_id: cvSentColumn.stage_def_id ?? undefined,
                  expected_state_version: expectedStateVersionOf(person.item),
                  acknowledge_eligibility: acknowledgeEligibility ? true : undefined,
                });
              },
              createShareLink: async ({ expiresInDays: linkDays }) => {
                const res = await candidateStageCvApi.share.create(
                  person.sourceStageId,
                  linkDays,
                );
                const suffix = res.data?.share_url_suffix ?? null;
                if (!suffix) throw new Error(BULK_CV_NO_LINK_ADDRESS_REASON);
                return { shareUrlSuffix: suffix };
              },
              saveClientRate: async (rate) => {
                await candidatesApi.setRecruitmentClientRate(person.candidateId, jobId, {
                  rate_value: rate.value,
                  rate_unit: rate.unit,
                  rate_currency: rate.currency,
                });
              },
            },
          ),
        askEligibility: (person, error) =>
          new Promise<boolean>((resolve) => {
            setAsking(true);
            const settle = (answer: boolean) => {
              setAsking(false);
              resolve(answer);
            };
            const opened = eligibility.intercept(
              error,
              () => settle(true),
              () => settle(false),
              // Pętla idzie po wielu osobach — okno musi mówić, o kogo pyta.
              person.fullName,
            );
            if (!opened) settle(false);
          }),
        isEligibilityWarning,
        isVersionConflict: isPipelineVersionConflict,
        describeError: (error) => extractErrorMsg(error),
      });
    } catch (e) {
      // `runBulkCvHandoff` zamienia porażki w wyniki per osoba — to jest
      // awaria samej pętli. Część ruchów mogła się już zapisać.
      showError(
        extractErrorMsg(e) ||
          "Wysyłka CV została przerwana — odśwież listę i sprawdź, kto jest już na „CV Wysłane”.",
      );
    } finally {
      // RAZ, po całej pętli — nie per osoba. Oba klucze: część konsumentów
      // trzyma `jobId` jako liczbę, część jako tekst.
      void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
      void queryClient.invalidateQueries({ queryKey: ["pipeline-scores"] });
      busyRef.current = false;
      setProgress(null);
      setAsking(false);
      onHandled?.();
    }
    if (outcomes.length > 0) {
      runCounter.current += 1;
      setResult({ run: runCounter.current, outcomes });
    }
  };

  const retryLink = async (target: BulkCvHandoffRetryTarget): Promise<string> => {
    const res = await candidateStageCvApi.share.create(
      target.sourceStageId,
      target.expiresInDays,
    );
    const suffix = res.data?.share_url_suffix ?? null;
    if (!suffix) throw new Error(BULK_CV_NO_LINK_ADDRESS_REASON);
    return suffix;
  };

  const canSubmit = daysValid && invalidRateIds.length === 0;
  const title = pending
    ? `Wyślij CV do klienta — ${peopleCountLabel(pending.rows.length)}`
    : "";

  const dialogs = (
    <>
      {pending ? (
        <Dialog
          open
          onOpenChange={(open) => {
            if (!open) setPending(null);
          }}
        >
          <DialogContent size="lg">
            <DialogHeader>
              <DialogTitle>{title}</DialogTitle>
              <DialogDescription>
                {jobTitle ? `${jobTitle}: ` : ""}każda osoba zostanie przeniesiona na „CV
                Wysłane”, a do jej CV firmowego powstanie link dla klienta. Osoby bez
                sfinalizowanego CV firmowego zostaną pominięte (bez przeniesienia).
              </DialogDescription>
            </DialogHeader>
            <DialogBody className="space-y-4">
              <div className="space-y-1">
                <Label htmlFor="bulk-cv-days">Ważność linków (dni)</Label>
                <Input
                  id="bulk-cv-days"
                  inputMode="numeric"
                  value={days}
                  onChange={(e) => setDays(e.target.value)}
                  aria-invalid={!daysValid}
                  className="w-28"
                />
                {!daysValid ? (
                  <p role="alert" className="text-xs text-destructive-muted-foreground">
                    Podaj liczbę dni od {BULK_CV_MIN_LINK_DAYS} do {BULK_CV_MAX_LINK_DAYS}.
                  </p>
                ) : null}
              </div>

              {canWriteClientRate ? (
                <fieldset className="space-y-2">
                  <legend className="text-sm font-medium text-foreground">
                    Stawka do klienta (opcjonalnie)
                  </legend>
                  <div className="space-y-1">
                    <Label htmlFor="bulk-cv-unit">Jednostka (wspólna)</Label>
                    <select
                      id="bulk-cv-unit"
                      value={unit}
                      onChange={(e) => setUnit(e.target.value as RateUnit)}
                      className="h-9 rounded-md border border-border bg-card px-2 text-sm text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary"
                    >
                      {RATE_UNITS.map((u) => (
                        <option key={u} value={u}>
                          {RATE_UNIT_LABELS[u]}
                        </option>
                      ))}
                    </select>
                  </div>
                  <ul className="max-h-64 space-y-2 overflow-y-auto pr-1">
                    {pending.rows.map((row) => {
                      const inputId = `bulk-cv-rate-${row.candidateId}`;
                      const invalid = invalidRateIds.includes(row.candidateId);
                      return (
                        <li key={row.candidateId} className="flex items-center gap-2">
                          <Label htmlFor={inputId} className="min-w-0 flex-1 truncate">
                            Stawka do klienta — {row.fullName}
                          </Label>
                          <Input
                            id={inputId}
                            inputMode="decimal"
                            placeholder="bez stawki"
                            value={rates[row.candidateId] ?? ""}
                            onChange={(e) =>
                              setRates((prev) => ({
                                ...prev,
                                [row.candidateId]: e.target.value,
                              }))
                            }
                            aria-invalid={invalid}
                            className="w-32"
                          />
                        </li>
                      );
                    })}
                  </ul>
                  {invalidRateIds.length > 0 ? (
                    <p role="alert" className="text-xs text-destructive-muted-foreground">
                      Stawka musi być liczbą większą od zera — albo zostaw pole puste.
                    </p>
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      Puste pole = bez stawki. Waluta: PLN.
                    </p>
                  )}
                </fieldset>
              ) : null}
            </DialogBody>
            <DialogFooter>
              <Button variant="ghost" onClick={() => setPending(null)}>
                Anuluj
              </Button>
              <Button
                disabled={!canSubmit}
                onClick={() => void run(pending.rows, pending.onHandled)}
              >
                Wyślij i utwórz linki
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      ) : null}

      {progress && !asking ? (
        <Dialog open onOpenChange={() => undefined}>
          <DialogContent
            size="sm"
            hideClose
            onEscapeKeyDown={(e) => e.preventDefault()}
            onPointerDownOutside={(e) => e.preventDefault()}
            onInteractOutside={(e) => e.preventDefault()}
          >
            <DialogHeader>
              <DialogTitle>Wyślij CV do klienta</DialogTitle>
              <DialogDescription>
                Nie zamykaj karty — linki pokażę po ostatniej osobie.
              </DialogDescription>
            </DialogHeader>
            <DialogBody>
              <p
                role="status"
                aria-live="polite"
                className="flex items-center gap-2 text-sm text-foreground"
              >
                <Loader2 className="size-4 animate-spin" aria-hidden />
                Wysyłam {progress.index + 1} z {progress.total}… {progress.name}
              </p>
            </DialogBody>
          </DialogContent>
        </Dialog>
      ) : null}

      {eligibility.dialog}

      {result ? (
        <BulkCvHandoffDialog
          key={result.run}
          open
          outcomes={result.outcomes}
          onRetryLink={retryLink}
          onClose={() => setResult(null)}
        />
      ) : null}
    </>
  );

  return { start, busy: progress != null, dialogs };
}
