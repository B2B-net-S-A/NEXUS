"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useSetEntitlement,
  type EmploymentType,
  type LeaveEntitlementRow,
} from "@/lib/api/hr";

interface EntitlementDialogProps {
  userId: number;
  name: string;
  year: number;
  current: LeaveEntitlementRow | undefined;
  /** Forma osoby: UoP — urlop z wymiarem; B2B — płatne dni przerwy z umowy (D6). */
  employmentType?: EmploymentType;
  /** Podpowiedź wymiaru 20/26 ze stażu w kartotece (D9, tylko UoP). */
  suggestedDays?: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const asInput = (value: string | null | undefined) =>
  value == null ? "" : String(Number(value));

/** Kadry: pula urlopowa na rok (pusta pula = osoba bez puli). */
export function EntitlementDialog({
  userId,
  name,
  year,
  current,
  employmentType = "uop",
  suggestedDays = null,
  open,
  onOpenChange,
}: EntitlementDialogProps) {
  const leave = employmentType === "uop";
  const { showToast } = useToast();
  const save = useSetEntitlement(userId);
  const [entitlement, setEntitlement] = useState(asInput(current?.entitlement_days));
  const [carried, setCarried] = useState(asInput(current?.carried_over_days) || "0");
  const [usedInitial, setUsedInitial] = useState(
    asInput(current?.used_initial_days) || "0",
  );
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    setError(null);
    save.mutate(
      {
        year,
        entitlement_days: entitlement.trim() === "" ? null : entitlement.replace(",", "."),
        carried_over_days: (carried || "0").replace(",", "."),
        used_initial_days: (usedInitial || "0").replace(",", "."),
        reason: reason.trim() || null,
      },
      {
        onSuccess: () => {
          showToast(leave ? "Pula urlopowa zapisana" : "Pula płatnych dni zapisana", "success");
          onOpenChange(false);
        },
        onError: (err) =>
          setError(apiErrorMessage(err, "Nie udało się zapisać puli.")),
      },
    );
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={leave ? `Pula urlopowa ${year} · ${name}` : `Płatne dni przerwy ${year} · ${name}`}
      description={
        leave
          ? "Dni podaje się w pełnych dniach albo połówkach (np. 2,5)."
          : "Tylko gdy umowa B2B przewiduje płatne dni przerwy. Dni ponad pulę są bez wynagrodzenia."
      }
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={save.isPending}>
            {save.isPending ? "Zapisywanie…" : "Zapisz pulę"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <FormField
          label="Pula na rok"
          htmlFor="hr-ent-days"
          description="Puste = bez puli."
        >
          <Input
            id="hr-ent-days"
            inputMode="decimal"
            value={entitlement}
            onChange={(event) => setEntitlement(event.target.value)}
          />
        </FormField>
        <FormField label="Zaległy z poprzedniego roku" htmlFor="hr-ent-carried">
          <Input
            id="hr-ent-carried"
            inputMode="decimal"
            value={carried}
            onChange={(event) => setCarried(event.target.value)}
          />
        </FormField>
        <FormField
          label="Wykorzystane przed NEXUSEM"
          htmlFor="hr-ent-initial"
          description="Dni z tego roku sprzed przejścia."
        >
          <Input
            id="hr-ent-initial"
            inputMode="decimal"
            value={usedInitial}
            onChange={(event) => setUsedInitial(event.target.value)}
          />
        </FormField>
        <FormField label="Powód zmiany" htmlFor="hr-ent-reason" className="sm:col-span-3">
          <Input
            id="hr-ent-reason"
            value={reason}
            maxLength={500}
            onChange={(event) => setReason(event.target.value)}
          />
        </FormField>
      </div>
      {leave && suggestedDays ? (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          Wymiar według stażu w kartotece: {suggestedDays} dni (20 poniżej 10 lat, 26 od 10
          lat). Przy starcie w trakcie roku albo części etatu policz proporcję.
          {entitlement !== String(suggestedDays) ? (
            <Button
              type="button"
              variant="quiet"
              size="sm"
              onClick={() => setEntitlement(String(suggestedDays))}
            >
              Wpisz {suggestedDays} dni
            </Button>
          ) : null}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="mt-4 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}
