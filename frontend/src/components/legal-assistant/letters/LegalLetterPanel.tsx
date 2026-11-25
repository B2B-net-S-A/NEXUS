"use client";

/**
 * Panel boczny „Napisz pismo” na stronie kontraktu (asystent prawny, część F).
 *
 * Szkic robi serwer (wzór albo model), „Zatwierdzam” sprawdza cytaty jeszcze
 * raz, a dopiero potem otwiera się okno maila NEXUSA (`SendEmailV2` z tematem
 * i treścią) albo powstaje DOCX do Dokumentów kontraktu. Nic nie wychodzi samo.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { SendEmailV2 } from "@/components/v2/modals/SendEmailV2";
import { apiErrorMessage } from "@/lib/api-error";
import { documentsHref } from "@/lib/b2b-documents";
import {
  approveLetter,
  availableKinds,
  defaultKind,
  draftLetter,
  letterDocx,
  letterFilename,
  letterKind,
  mailSubject,
  saveLetterToDocuments,
  type LetterCheck,
  type LetterContractFacts,
  type LetterDraft,
  type LetterKindKey,
  type LetterOptions,
} from "@/lib/legal-letters";

import { LetterPanelView } from "./LetterPanelView";

const NEEDS_INPUT: readonly LetterKindKey[] = ["penalty_note", "client_letter"];

export interface LegalLetterPanelProps {
  contractId: number;
  contract: LetterContractFacts;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialKind?: string | null;
  /** „DOCX do Dokumentów” — prawo dodawania plików kontraktu. */
  canSave: boolean;
}

function amountOf(value: string): number | null {
  const parsed = Number(value.replace(/\s/g, "").replace(",", "."));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function conflictChecks(err: unknown): LetterCheck[] | null {
  const detail = (err as { response?: { status?: number; data?: { detail?: { checks?: LetterCheck[] } } } } | null)
    ?.response;
  if (detail?.status !== 409) return null;
  return detail.data?.detail?.checks ?? null;
}

export function LegalLetterPanel({ contractId, contract, open, onOpenChange, initialKind, canSave }: LegalLetterPanelProps) {
  const queryClient = useQueryClient();
  const kinds = availableKinds(contract);
  const [kind, setKind] = useState<LetterKindKey>(() => defaultKind(contract, initialKind));
  const [draft, setDraft] = useState<LetterDraft | null>(null);
  const [text, setText] = useState("");
  const [instruction, setInstruction] = useState("");
  const [penaltyAmount, setPenaltyAmount] = useState("");
  const [originalConfirmed, setOriginalConfirmed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [approved, setApproved] = useState(false);
  const [approvedChecks, setApprovedChecks] = useState<LetterCheck[] | null>(null);
  const [busy, setBusy] = useState<"approve" | "docx" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [savedName, setSavedName] = useState<string | null>(null);
  const [mailOpen, setMailOpen] = useState(false);
  const request = useRef(0);

  useEffect(() => {
    if (open) setKind(defaultKind(contract, initialKind));
    // Rodzaj z adresu (`?pismo=`) przy każdym otwarciu; kontrakt się nie zmienia.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialKind]);

  const options = useCallback(
    (forKind: LetterKindKey): LetterOptions => ({
      kind: forKind,
      instruction,
      original_confirmed: originalConfirmed,
      penalty_amount: forKind === "penalty_note" ? amountOf(penaltyAmount) : null,
    }),
    [instruction, originalConfirmed, penaltyAmount],
  );

  const prepare = useCallback(
    async (forKind: LetterKindKey) => {
      const id = ++request.current;
      setLoading(true);
      setError(null);
      setActionError(null);
      setApproved(false);
      setApprovedChecks(null);
      setSavedName(null);
      try {
        const next = await draftLetter(contractId, options(forKind));
        if (id !== request.current) return;
        setDraft(next);
        setText(next.text);
      } catch (err) {
        if (id !== request.current) return;
        setDraft(null);
        setError(apiErrorMessage(err, "Nie udało się przygotować szkicu pisma."));
      } finally {
        if (id === request.current) setLoading(false);
      }
    },
    [contractId, options],
  );

  // Szkic bez danych od człowieka (odpowiedź, wzory) przygotowuje się od razu.
  useEffect(() => {
    if (!open) return;
    setDraft(null);
    setText("");
    if (!NEEDS_INPUT.includes(kind)) void prepare(kind);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, kind]);

  const approve = async () => {
    if (!draft) return;
    setBusy("approve");
    setActionError(null);
    try {
      const result = await approveLetter(contractId, options(kind), text);
      setApproved(true);
      setApprovedChecks(result.checks);
      if (result.task_key) await queryClient.invalidateQueries({ queryKey: ["legal-tasks"] });
    } catch (err) {
      const checks = conflictChecks(err);
      if (checks) setApprovedChecks(checks);
      setActionError(apiErrorMessage(err, "Nie udało się zatwierdzić pisma."));
    } finally {
      setBusy(null);
    }
  };

  const saveDocx = async () => {
    if (!draft) return;
    setBusy("docx");
    setActionError(null);
    try {
      const blob = await letterDocx(contractId, options(kind), text);
      const filename = letterFilename(draft.label, new Date().toISOString().slice(0, 10));
      await saveLetterToDocuments(contractId, blob, filename);
      setSavedName(filename);
      await queryClient.invalidateQueries({ queryKey: ["contract-documents", contractId] });
      await queryClient.invalidateQueries({ queryKey: ["contract-document-folders", contractId] });
    } catch (err) {
      setActionError(apiErrorMessage(err, "Nie udało się zapisać pisma w Dokumentach kontraktu."));
    } finally {
      setBusy(null);
    }
  };

  const def = letterKind(kind);
  const recipient = draft?.recipient ?? null;
  return (
    <>
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent side="right" size="lg" className="w-full p-0 h-dvh">
          <SheetTitle className="sr-only">Pismo</SheetTitle>
          <SheetDescription className="sr-only">Szkic pisma asystenta prawnego — nic nie wysłano</SheetDescription>
          <LetterPanelView
            kinds={kinds}
            kind={kind}
            onKindChange={(next) => {
              setOriginalConfirmed(false);
              setKind(next);
            }}
            draft={draft}
            loading={loading}
            error={error}
            text={text}
            onTextChange={setText}
            instruction={instruction}
            onInstructionChange={setInstruction}
            penaltyAmount={penaltyAmount}
            onPenaltyAmountChange={setPenaltyAmount}
            onPrepare={() => void prepare(kind)}
            originalConfirmed={originalConfirmed}
            onConfirmOriginal={() => setOriginalConfirmed(true)}
            onSwitchToAgreement={() => setKind("termination_agreement")}
            approved={approved}
            approvedChecks={approvedChecks}
            busy={busy}
            actionError={actionError}
            savedName={savedName}
            canSave={canSave}
            canMail={recipient?.candidate_id != null}
            generatorHref={def?.template ? documentsHref({ newType: def.template, contractId }) : null}
            onApprove={() => void approve()}
            onOpenMail={() => setMailOpen(true)}
            onSaveDocx={() => void saveDocx()}
          />
        </SheetContent>
      </Sheet>
      {draft && recipient?.candidate_id != null && (
        <SendEmailV2
          open={mailOpen}
          onOpenChange={setMailOpen}
          candidateId={recipient.candidate_id}
          candidateName={recipient.name}
          candidateEmail={recipient.kind === "partner" ? (recipient.email ?? "") : ""}
          defaultSubject={mailSubject(draft.subject)}
          defaultBody={text}
        />
      )}
    </>
  );
}
