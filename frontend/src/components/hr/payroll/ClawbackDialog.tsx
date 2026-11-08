"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useCancelClawback,
  useRegisterClawback,
  type BonusClawback,
  type BonusRow,
} from "@/lib/api/hr-payroll";
import { formatMoney } from "@/lib/money";

const NOTE_MIN = 3;

type ClawbackDialogProps =
  | { mode: "register"; bonus: BonusRow; onClose: () => void }
  | { mode: "cancel"; clawback: BonusClawback; onClose: () => void };

/**
 * Płace: „Zwrot z gwarancji” przy przyznanej premii DL albo zdjęcie długu
 * (05.11.2026). Powód jest obowiązkowy — zostaje w śladzie i, przy zwrocie,
 * osoba widzi go w „Moim czasie”.
 */
export function ClawbackDialog(props: ClawbackDialogProps) {
  const { showToast } = useToast();
  const register = useRegisterClawback();
  const cancel = useCancelClawback();
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const registering = props.mode === "register";
  const pending = register.isPending || cancel.isPending;
  const subject = registering
    ? `${props.bonus.description ?? "Premia DL"} · ${props.bonus.recipient_name ?? "Osoba"} · ${formatMoney(
        props.bonus.amount,
        props.bonus.currency,
      )}`
    : `${props.clawback.description ?? "Premia DL"} · ${props.clawback.recipient_name ?? "Osoba"} · ${formatMoney(
        props.clawback.amount,
        props.clawback.currency,
      )}`;

  const submit = () => {
    const text = note.trim();
    if (text.length < NOTE_MIN) {
      setError(`Podaj powód (co najmniej ${NOTE_MIN} znaki).`);
      return;
    }
    setError(null);
    const handlers = {
      onSuccess: () => {
        showToast(registering ? "Zwrot z gwarancji dodany" : "Zwrot zdjęty", "success");
        props.onClose();
      },
      onError: (err: unknown) =>
        setError(apiErrorMessage(err, "Nie udało się zapisać zwrotu.")),
    };
    if (props.mode === "register") {
      register.mutate({ bonusId: props.bonus.id, note: text }, handlers);
    } else {
      cancel.mutate({ id: props.clawback.id, note: text }, handlers);
    }
  };

  return (
    <AppModal
      open
      onOpenChange={(value) => {
        if (!value) props.onClose();
      }}
      title={registering ? "Zwrot premii z gwarancji?" : "Zdjąć zwrot z gwarancji?"}
      description={subject}
      footer={
        <>
          <Button variant="ghost" onClick={props.onClose}>
            Wróć
          </Button>
          <Button
            variant={registering ? "primary" : "destructive"}
            onClick={submit}
            disabled={pending}
          >
            {pending ? "Zapisywanie…" : registering ? "Dodaj zwrot" : "Zdejmij zwrot"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <FormField label="Powód" htmlFor="clawback-note">
          <Input
            id="clawback-note"
            value={note}
            maxLength={500}
            placeholder={
              registering ? "np. konsultant odszedł 04.11, kontrakt jeszcze otwarty" : undefined
            }
            onChange={(event) => setNote(event.target.value)}
          />
        </FormField>
        <p className="text-sm text-muted-foreground">
          {registering
            ? "Cała kwota potrąci się sama z kolejnych premii tej osoby, najwyżej do ich sumy w miesiącu. Osoba zobaczy zwrot w „Moim czasie”."
            : "Potrącenia z zamkniętych miesięcy zostają; reszta przestaje się potrącać. Automat nie założy tego zwrotu ponownie."}
        </p>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}
