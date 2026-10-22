"use client";

import { useId, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage } from "@/lib/api-error";
import {
  OWNER_REASON_LABELS,
  useCareOwners,
  useSetContractOwner,
  type ConsultantCardData,
  type OwnerReason,
} from "@/lib/api/care";

const DEFAULT_OWNER = "default";
const REASONS = Object.keys(OWNER_REASON_LABELS) as OwnerReason[];

interface OwnerDialogProps {
  card: ConsultantCardData;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * „Zmień opiekuna” z menu „Więcej” karty — ta sama lista co dawny wybór
 * w zakładce „Opieka” (pula bez „nie przypisuj”), z opcjonalnym powodem na osi.
 */
export function OwnerDialog({ card, open, onOpenChange }: OwnerDialogProps) {
  const { showToast } = useToast();
  const ids = { owner: useId(), reason: useId() };
  const owners = useCareOwners(open);
  const save = useSetContractOwner(card.contract_id);
  const [value, setValue] = useState(
    card.owner.source === "contract" && card.owner.user_id != null
      ? String(card.owner.user_id)
      : DEFAULT_OWNER,
  );
  const [reason, setReason] = useState<OwnerReason | "">("");
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    setError(null);
    save.mutate(
      { userId: value === DEFAULT_OWNER ? null : Number(value), reason: reason || null },
      {
        onSuccess: () => {
          showToast("Opiekun zmieniony", "success");
          onOpenChange(false);
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zmienić opiekuna.")),
      },
    );
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Zmień opiekuna"
      description={`${card.candidate_name ?? "Konsultant"} · ${card.client_name}. Zmiana zostaje w historii z powodem.`}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} loading={save.isPending}>
            Zapisz
          </Button>
        </>
      }
    >
      <div className="grid gap-3">
        <FormField label="Opiekun" htmlFor={ids.owner}>
          <Select value={value} onValueChange={setValue}>
            <SelectTrigger id={ids.owner}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={DEFAULT_OWNER}>Domyślny (klient albo DL)</SelectItem>
              {(owners.data ?? []).map((owner) => (
                <SelectItem key={owner.id} value={String(owner.id)}>
                  {owner.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        {owners.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {apiErrorMessage(owners.error, "Nie udało się wczytać listy opiekunów.")}
          </p>
        ) : null}
        <FormField label="Powód" htmlFor={ids.reason} description="Opcjonalnie — widać go w historii.">
          <Select value={reason} onValueChange={(next) => setReason(next as OwnerReason)}>
            <SelectTrigger id={ids.reason}>
              <SelectValue placeholder="Bez powodu" />
            </SelectTrigger>
            <SelectContent>
              {REASONS.map((key) => (
                <SelectItem key={key} value={key}>
                  {OWNER_REASON_LABELS[key]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}
