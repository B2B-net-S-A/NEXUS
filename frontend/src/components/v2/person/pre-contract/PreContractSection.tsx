"use client";

/**
 * Sekcja „Umowa przedwstępna” w panelu osoby (zakładka „Umowa”, 0504).
 *
 * Decyzje Artura 21.10.2026: prośba przy osobie (DL, HoR albo rekruter),
 * wystawia rekruter prowadzący, każdy krok z datą i osobą, każda forma
 * podpisu, brak podpisu nie blokuje ruchu. Stan i plakietkę liczy serwer.
 */

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Bell, BellOff, Download, FileSignature, Loader2 } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  PRE_CONTRACT_TONE_CLASS,
  invalidatePreContract,
  preContractsApi,
  usePreContractPair,
  type PreContractPairDocument,
  type PreContractRequest,
} from "@/lib/api/preContracts";
import { downloadBlob, parseDispositionFilename } from "@/lib/cv-generator";
import { cn } from "@/lib/utils";

import {
  PreContractPenaltyDialog,
  PreContractReasonDialog,
  PreContractRequestDialog,
  PreContractUploadDialog,
  PreContractWithdrawalDialog,
} from "./PreContractDialogs";
import { PreContractIssueDialog } from "./PreContractIssueDialog";

function dayPl(iso?: string | null): string {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

function shortDay(iso?: string | null): string {
  return dayPl(iso).slice(0, 5);
}

interface Step {
  key: string;
  label: string;
  done: boolean;
  meta: string;
}

/** Kroki drogi umowy — opis kroku z historii (kto, kiedy). */
export function preContractSteps(req: PreContractRequest): Step[] {
  const event = (kind: string) => req.events.find((e) => e.kind === kind);
  const meta = (kind: string, fallback?: string | null) => {
    const e = event(kind);
    if (!e) return fallback ? shortDay(fallback) : "";
    return [shortDay(e.at), e.actor?.name].filter(Boolean).join(" · ");
  };
  return [
    {
      key: "requested",
      label: `Prośba — ${req.needed_before_label}`,
      done: true,
      meta: meta("requested", req.requested_at),
    },
    { key: "issued", label: "Wystawiona", done: req.document_id != null, meta: meta("issued") },
    { key: "sent", label: "Wysłana kandydatowi", done: req.sent_at != null, meta: meta("sent", req.sent_at) },
    {
      key: "candidate_signed",
      label: req.candidate_signature_form_label
        ? `Kandydat podpisał — ${req.candidate_signature_form_label}`
        : "Kandydat podpisał",
      done: req.candidate_signed_at != null,
      meta: meta("candidate_signed", req.candidate_signed_at),
    },
    {
      key: "company_signed",
      label: "Podpis za B2B Network",
      done: req.company_signed_at != null,
      meta: meta("company_signed", req.company_signed_at),
    },
  ];
}

type DialogKind =
  | "request"
  | "issue"
  | "upload-candidate"
  | "upload-company"
  | "cancel"
  | "refused"
  | "withdrawal"
  | "penalty";

export function PreContractSection({
  candidateId,
  jobId,
  personLabel,
  readOnly = false,
}: {
  candidateId: number;
  jobId: number;
  personLabel: string;
  readOnly?: boolean;
}) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const pair = usePreContractPair(candidateId, jobId);
  const [dialog, setDialog] = useState<DialogKind | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = () => invalidatePreContract(queryClient, jobId);
  const onDone = () => refresh();

  const act = async (key: string, fn: () => Promise<unknown>, ok: string, fail: string) => {
    setBusy(key);
    try {
      await fn();
      showSuccess(ok);
      refresh();
    } catch (e) {
      showError(apiErrorMessage(e, fail));
    } finally {
      setBusy(null);
    }
  };

  const download = async (req: PreContractRequest, kind: "candidate" | "company") => {
    try {
      const res = await preContractsApi.downloadFile(req.id, kind);
      const fallback = (kind === "candidate" ? req.candidate_file_name : req.company_file_name) ?? "umowa.pdf";
      downloadBlob(res.data, parseDispositionFilename(String(res.headers["content-disposition"] ?? ""), fallback));
    } catch (e) {
      showError(apiErrorMessage(e, "Nie udało się pobrać pliku."));
    }
  };

  if (pair.isLoading) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        Sprawdzam umowę przedwstępną…
      </p>
    );
  }
  if (pair.isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        Nie udało się sprawdzić umowy przedwstępnej.{" "}
        <button type="button" className="font-medium underline" onClick={() => void pair.refetch()}>
          Ponów
        </button>
      </p>
    );
  }
  if (!pair.isSuccess) return null;

  const current = pair.data.current;
  const lastClosed = pair.data.history[0] ?? null;
  const shown = current ?? lastClosed;
  const unlinked: PreContractPairDocument[] = pair.data.documents.filter((d) => !d.linked);

  return (
    <section
      aria-labelledby="pre-contract-title"
      className="space-y-3 rounded-lg border border-border p-4"
      data-testid="pre-contract-section"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="pre-contract-title" className="flex items-center gap-2 text-sm font-semibold">
          <FileSignature className="h-4 w-4 text-muted-foreground" aria-hidden />
          Umowa przedwstępna
        </h3>
        {shown ? (
          <span
            className={cn("rounded px-2 py-0.5 text-xs font-semibold", PRE_CONTRACT_TONE_CLASS[shown.badge.tone])}
            title={shown.badge.detail}
            data-testid="pre-contract-badge"
          >
            {shown.badge.label}
          </span>
        ) : null}
      </div>

      {!current ? (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">
            {lastClosed
              ? `Ostatnia: ${lastClosed.state_label.toLowerCase()} (${dayPl(lastClosed.closed_at)}).`
              : "Nikt nie prosił o umowę przedwstępną dla tej osoby."}
          </p>
          {lastClosed?.can_decide_penalty ? (
            <Button size="sm" onClick={() => setDialog("penalty")}>
              Decyzja o karze
            </Button>
          ) : null}
          {!readOnly ? (
            <Button size="sm" variant="outline" onClick={() => setDialog("request")} data-testid="pre-contract-request">
              Poproś o przedwstępną
            </Button>
          ) : null}
        </div>
      ) : (
        <>
          <ol className="space-y-2" aria-label="Kroki umowy">
            {preContractSteps(current).map((step, i, all) => {
              const next = !step.done && (i === 0 || all[i - 1].done);
              return (
                <li key={step.key} className="flex items-start gap-3">
                  <span
                    aria-hidden
                    className={cn(
                      "mt-1 h-3 w-3 shrink-0 rounded-full",
                      step.done ? "bg-success" : next ? "border-2 border-primary bg-background" : "border-2 border-border bg-background",
                    )}
                  />
                  <span className="text-sm">
                    <span className={cn(!step.done && !next && "text-muted-foreground")}>{step.label}</span>
                    {step.meta ? <span className="block text-xs text-muted-foreground">{step.meta}</span> : null}
                    <span className="sr-only">{step.done ? " — zrobione" : next ? " — teraz" : " — później"}</span>
                  </span>
                </li>
              );
            })}
            <li className="flex items-start gap-3">
              <span aria-hidden className="mt-1 h-3 w-3 shrink-0 rounded-full border-2 border-border bg-background" />
              <span className="text-sm text-muted-foreground">
                {current.valid_until ? `Obowiązuje do ${dayPl(current.valid_until)}` : "Data ważności z umowy"}
                {current.b2b_deadline ? (
                  <span className="block text-xs font-medium text-destructive">
                    Umowa B2B do {dayPl(current.b2b_deadline)}
                  </span>
                ) : null}
              </span>
            </li>
          </ol>

          <dl className="grid grid-cols-[9rem_1fr] gap-x-3 gap-y-1 text-xs">
            <dt className="text-muted-foreground">Poprosił(a)</dt>
            <dd>
              {current.requested_by?.name ?? "—"}
              {current.reason ? <span className="block text-muted-foreground">„{current.reason}”</span> : null}
            </dd>
            <dt className="text-muted-foreground">Wystawia</dt>
            <dd>{current.assignee?.name ?? "—"}</dd>
            <dt className="text-muted-foreground">Obserwują</dt>
            <dd className="flex flex-wrap items-center gap-x-2">
              <span>{current.watchers.map((w) => w.name).join(", ") || "—"}</span>
              <button
                type="button"
                className="inline-flex items-center gap-1 font-medium text-primary underline-offset-2 hover:underline"
                onClick={() =>
                  void act(
                    "watch",
                    () => (current.watching ? preContractsApi.unwatch(current.id) : preContractsApi.watch(current.id)),
                    current.watching ? "Nie obserwujesz już tej umowy." : "Obserwujesz tę umowę.",
                    "Nie udało się zmienić obserwowania.",
                  )
                }
              >
                {current.watching ? <BellOff className="h-3 w-3" aria-hidden /> : <Bell className="h-3 w-3" aria-hidden />}
                {current.watching ? "Przestań obserwować" : "Obserwuj"}
              </button>
            </dd>
          </dl>

          {current.candidate_file_name || current.company_file_name ? (
            <div className="flex flex-wrap gap-2">
              {current.candidate_file_name ? (
                <Button size="sm" variant="ghost" onClick={() => void download(current, "candidate")}>
                  <Download className="mr-1 h-3.5 w-3.5" aria-hidden />
                  Od kandydata
                </Button>
              ) : null}
              {current.company_file_name ? (
                <Button size="sm" variant="ghost" onClick={() => void download(current, "company")}>
                  <Download className="mr-1 h-3.5 w-3.5" aria-hidden />
                  Podpisana obustronnie
                </Button>
              ) : null}
            </div>
          ) : null}

          {!readOnly ? (
            <div className="flex flex-wrap gap-2">
              {current.state === "requested" ? (
                <>
                  <Button size="sm" onClick={() => setDialog("issue")} data-testid="pre-contract-issue">
                    Wystaw umowę
                  </Button>
                  {unlinked.map((d) => (
                    <Button
                      key={d.id}
                      size="sm"
                      variant="outline"
                      disabled={busy === `link-${d.id}`}
                      onClick={() =>
                        void act(
                          `link-${d.id}`,
                          () => preContractsApi.linkDocument(current.id, d.id),
                          "Umowa podpięta.",
                          "Nie udało się podpiąć umowy.",
                        )
                      }
                    >
                      Podepnij umowę z {dayPl(d.document_date)}
                    </Button>
                  ))}
                </>
              ) : null}
              {current.state === "issued" ? (
                <Button
                  size="sm"
                  disabled={busy === "sent"}
                  onClick={() =>
                    void act("sent", () => preContractsApi.markSent(current.id), "Oznaczono jako wysłaną.", "Nie udało się zapisać.")
                  }
                  data-testid="pre-contract-sent"
                >
                  Oznacz jako wysłaną kandydatowi
                </Button>
              ) : null}
              {current.state === "issued" || current.state === "sent" ? (
                <>
                  <Button size="sm" variant={current.state === "sent" ? "primary" : "outline"} onClick={() => setDialog("upload-candidate")}>
                    Wgraj podpisaną przez kandydata
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setDialog("refused")}>
                    Kandydat odmówił
                  </Button>
                </>
              ) : null}
              {current.state === "candidate_signed" ? (
                <Button size="sm" onClick={() => setDialog("upload-company")} data-testid="pre-contract-company">
                  Wgraj podpisaną przez firmę
                </Button>
              ) : null}
              {current.state === "signed" ? (
                <>
                  <Button size="sm" variant="outline" onClick={() => setDialog("withdrawal")}>
                    Kandydat zrezygnował…
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy === "fulfilled"}
                    onClick={() =>
                      void act(
                        "fulfilled",
                        () => preContractsApi.fulfilled(current.id),
                        "Umowa zrealizowana.",
                        "Nie udało się zapisać.",
                      )
                    }
                  >
                    Zrealizowana
                  </Button>
                </>
              ) : null}
              {current.can_withdraw ? (
                <Button
                  size="sm"
                  variant="quiet"
                  disabled={busy === "withdraw"}
                  onClick={() =>
                    void act("withdraw", () => preContractsApi.withdraw(current.id), "Prośba wycofana.", "Nie udało się wycofać prośby.")
                  }
                >
                  Wycofaj prośbę
                </Button>
              ) : current.state !== "requested" ? (
                <Button size="sm" variant="quiet" onClick={() => setDialog("cancel")}>
                  Anuluj umowę
                </Button>
              ) : null}
            </div>
          ) : null}
        </>
      )}

      {dialog === "request" ? (
        <PreContractRequestDialog
          open
          onOpenChange={(o) => !o && setDialog(null)}
          candidateId={candidateId}
          jobId={jobId}
          personLabel={personLabel}
          onDone={onDone}
        />
      ) : null}
      {current && dialog === "issue" ? (
        <PreContractIssueDialog open onOpenChange={(o) => !o && setDialog(null)} request={current} onDone={onDone} />
      ) : null}
      {current && (dialog === "upload-candidate" || dialog === "upload-company") ? (
        <PreContractUploadDialog
          open
          onOpenChange={(o) => !o && setDialog(null)}
          request={current}
          kind={dialog === "upload-candidate" ? "candidate" : "company"}
          onDone={onDone}
        />
      ) : null}
      {current && (dialog === "cancel" || dialog === "refused") ? (
        <PreContractReasonDialog
          open
          onOpenChange={(o) => !o && setDialog(null)}
          request={current}
          mode={dialog}
          onDone={onDone}
        />
      ) : null}
      {current && dialog === "withdrawal" ? (
        <PreContractWithdrawalDialog open onOpenChange={(o) => !o && setDialog(null)} request={current} onDone={onDone} />
      ) : null}
      {lastClosed && dialog === "penalty" ? (
        <PreContractPenaltyDialog open onOpenChange={(o) => !o && setDialog(null)} request={lastClosed} onDone={onDone} />
      ) : null}
    </section>
  );
}
