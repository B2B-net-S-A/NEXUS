"use client";

import { useRef, type ChangeEvent } from "react";
import { Paperclip, X } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  downloadLeaveProof,
  useAttachLeaveProof,
  useRemoveLeaveProof,
  type LeaveProof,
  type LeaveRequestRow,
} from "@/lib/api/hr-leave";
import { CALM_EMPTY, CALM_SUBLINE } from "@/lib/calm-table";

import { PROOF_ACCEPT, canAttachMore, proofProblem, proofSummary } from "./leave-proofs";

function useDownload(row: LeaveRequestRow, scope: "own" | "team") {
  const { showToast } = useToast();
  return (proof: LeaveProof) => {
    void downloadLeaveProof(row.id, proof, scope).catch((err: unknown) =>
      showToast(apiErrorMessage(err, "Nie udało się pobrać załącznika."), "error"),
    );
  };
}

function ProofLink({ proof, onOpen }: { proof: LeaveProof; onOpen: (proof: LeaveProof) => void }) {
  return (
    <button
      type="button"
      className="inline-flex max-w-[220px] items-center gap-1 truncate text-left text-xs text-primary hover:underline"
      title={proof.file_name}
      onClick={() => onOpen(proof)}
    >
      <Paperclip className="h-3 w-3 shrink-0" aria-hidden />
      <span className="truncate">{proof.file_name}</span>
    </button>
  );
}

/**
 * Akceptacje i historia: „Załącznik ✓”. Kadry (serwer oddał listę) pobierają
 * plik; przełożony widzi tylko, że jest — treść bywa aktem zgonu (D6).
 */
export function ApproverProofNote({ row }: { row: LeaveRequestRow }) {
  const open = useDownload(row, "team");
  const summary = proofSummary(row);
  if (!summary) return null;
  const files = row.proofs ?? [];
  if (files.length === 0) {
    return <span className={CALM_SUBLINE}>{summary}</span>;
  }
  return (
    <span className={`${CALM_SUBLINE} flex flex-wrap items-center gap-x-2`}>
      <span>{summary}</span>
      {files.map((proof) => (
        <ProofLink key={proof.id} proof={proof} onOpen={open} />
      ))}
    </span>
  );
}

/** „Moje nieobecności”: moje pliki przy wniosku, „Dołącz plik” i usunięcie pomyłki. */
export function MyProofsCell({ row }: { row: LeaveRequestRow }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const attach = useAttachLeaveProof();
  const remove = useRemoveLeaveProof();
  const open = useDownload(row, "own");
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const files = row.proofs ?? [];
  const canAdd = canAttachMore(row);

  const onPick = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    event.target.value = "";
    if (!file) return;
    const problem = proofProblem(file);
    if (problem) {
      showToast(problem, "error");
      return;
    }
    attach.mutate(
      { id: row.id, file },
      {
        onSuccess: () => showToast("Załącznik dołączony", "success"),
        onError: (err) =>
          showToast(apiErrorMessage(err, "Nie udało się dołączyć pliku."), "error"),
      },
    );
  };

  const removeProof = async (proof: LeaveProof) => {
    const ok = await askConfirm({
      title: "Usunąć załącznik?",
      description: `${proof.file_name} zniknie z wniosku i z Twoich dokumentów. Kadry zobaczą ślad, że plik był.`,
      confirmLabel: "Usuń",
      cancelLabel: "Zostaw",
      variant: "destructive",
    });
    if (!ok) return;
    remove.mutate(
      { id: row.id, proofId: proof.id },
      {
        onSuccess: () => showToast("Załącznik usunięty", "success"),
        onError: (err) =>
          showToast(apiErrorMessage(err, "Nie udało się usunąć pliku."), "error"),
      },
    );
  };

  if (files.length === 0 && !canAdd) {
    return <span className={CALM_EMPTY}>—</span>;
  }
  return (
    <div className="flex flex-col items-start gap-0.5">
      {files.map((proof) => (
        <span key={proof.id} className="inline-flex items-center gap-1">
          <ProofLink proof={proof} onOpen={open} />
          {proof.can_remove ? (
            <button
              type="button"
              aria-label={`Usuń ${proof.file_name}`}
              className="rounded p-0.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
              disabled={remove.isPending}
              onClick={() => void removeProof(proof)}
            >
              <X className="h-3 w-3" aria-hidden />
            </button>
          ) : null}
        </span>
      ))}
      {canAdd ? (
        <>
          <Button
            size="sm"
            variant="tertiary"
            className="h-6 px-0"
            disabled={attach.isPending}
            onClick={() => inputRef.current?.click()}
          >
            {attach.isPending ? "Wysyłanie…" : files.length ? "Dołącz kolejny" : "Dołącz plik"}
          </Button>
          <input
            ref={inputRef}
            type="file"
            accept={PROOF_ACCEPT}
            className="sr-only"
            aria-label="Dołącz plik do wniosku"
            tabIndex={-1}
            onChange={onPick}
          />
        </>
      ) : null}
      {confirmDialog}
    </div>
  );
}
