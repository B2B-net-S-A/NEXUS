"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useDecideApproval,
  type ApprovalDecision,
  type ApprovalRequestRow,
} from "@/lib/api/hr-approvals";

import { approveLabel, canChangeAmount, moneyPl } from "./approvals-format";

export type DecisionMode = ApprovalDecision | "approve_amount";

const TITLES: Record<DecisionMode, string> = {
  approve: "Zatwierdzić zgodę?",
  approve_amount: "Zatwierdzić inną kwotę?",
  reject: "Odrzucić zgodę?",
  return: "Dopytać autora?",
};

const NOTE_LABEL: Record<DecisionMode, string> = {
  approve: "Uwaga dla autora (opcjonalnie)",
  approve_amount: "Dlaczego inna kwota (opcjonalnie)",
  reject: "Powód — trafi do autora",
  return: "O co pytasz — autor poprawi i wyśle znowu",
};

interface DecisionDialogProps {
  row: ApprovalRequestRow | null;
  mode: DecisionMode | null;
  onClose: () => void;
}

/** Decyzja o zgodzie: zatwierdź (także inną kwotą), odrzuć z powodem albo dopytaj. */
export function DecisionDialog({ row, mode, onClose }: DecisionDialogProps) {
  const decide = useDecideApproval();
  const { showToast } = useToast();
  const [note, setNote] = useState("");
  const [amount, setAmount] = useState("");
  const [error, setError] = useState<string | null>(null);
  const open = row !== null && mode !== null;
  const needsNote = mode === "reject" || mode === "return";

  const close = () => {
    setNote("");
    setAmount("");
    setError(null);
    onClose();
  };

  const submit = () => {
    if (!row || !mode) return;
    if (needsNote && note.trim().length < 3) {
      setError("Napisz jedno zdanie — trafi do autora zgody.");
      return;
    }
    const normalized = amount.replace(/\s/g, "").replace(",", ".");
    if (mode === "approve_amount" && !(Number(normalized) > 0)) {
      setError("Podaj kwotę większą od zera.");
      return;
    }
    decide.mutate(
      {
        id: row.id,
        action: mode === "approve_amount" ? "approve" : mode,
        amount: mode === "approve_amount" ? normalized : null,
        note: note.trim() || null,
      },
      {
        onSuccess: (result) => {
          showToast(
            result.status === "pending_final"
              ? "Poparte — zgoda czeka na zatwierdzającego."
              : result.status === "approved"
                ? "Zatwierdzone."
                : result.status === "returned"
                  ? "Pytanie wysłane do autora."
                  : "Odrzucone.",
            "success",
          );
          close();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać decyzji.")),
      },
    );
  };

  const confirmLabel =
    mode === "reject"
      ? "Odrzuć"
      : mode === "return"
        ? "Wyślij pytanie"
        : row
          ? approveLabel(row)
          : "Zatwierdź";

  return (
    <AppModal
      open={open}
      onOpenChange={(next) => (next ? undefined : close())}
      title={mode ? TITLES[mode] : ""}
      description={row ? `${row.kind_label} · ${row.title} · ${row.amount_text}` : undefined}
      footer={
        <>
          <Button variant="ghost" onClick={close}>
            Zostaw
          </Button>
          <Button
            variant={mode === "reject" ? "destructive" : "primary"}
            onClick={submit}
            disabled={decide.isPending}
          >
            {decide.isPending ? "Zapisywanie…" : confirmLabel}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {mode === "approve_amount" && row && canChangeAmount(row) ? (
          <FormField
            label={`Kwota (wniosek: ${moneyPl(row.amount, row.currency)})`}
            htmlFor="approval-amount"
            required
          >
            <Input
              id="approval-amount"
              inputMode="decimal"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
          </FormField>
        ) : null}
        {mode === "approve" && row && approveLabel(row) === "Popieram" ? (
          <p className="text-sm text-muted-foreground">
            Kwota jest ponad Twój próg — poparcie przekaże zgodę do:{" "}
            {row.final_approver_names.join(", ") || "zatwierdzającego"}.
          </p>
        ) : null}
        <FormField
          label={mode ? NOTE_LABEL[mode] : ""}
          htmlFor="approval-note"
          error={error ?? undefined}
          required={needsNote}
        >
          <Textarea
            id="approval-note"
            rows={3}
            maxLength={1000}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </FormField>
      </div>
    </AppModal>
  );
}
