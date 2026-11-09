"use client";

/**
 * „Szczegóły administracyjne” podpisanego kontraktu (decyzje Artura 06.11.2026):
 * replacement, „za kogo” i kandydat wskazany przez klienta. W Generatorze te
 * pola wpisuje się przed umową; tu Płace (i osoby, które oznaczają podpis)
 * poprawiają je po podpisie, z powodem. Zapis od razu przelicza premie
 * kontraktu: gwarancja DL, brak premii za kandydata od klienta.
 */

import { useState } from "react";
import { ClipboardList } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { ReplacedPicker } from "@/components/v2/b2b-generator/AgreementAdminDetailsCard";
import { apiErrorMessage } from "@/lib/api-error";
import type { B2BReplaceableContract } from "@/lib/api";
import { useHrConfig } from "@/lib/api/hr";
import {
  useContractAdminDetails,
  useSaveContractAdminDetails,
  type ContractAdminDetails,
} from "@/lib/api/hr-payroll";
import { hasPermission } from "@/lib/permissions";
import { useAuthStore } from "@/store/auth";

function yesNo(value: boolean | null): string {
  if (value === null) return "nie zapisano";
  return value ? "Tak" : "Nie";
}

function YesNoField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean | null;
  onChange: (value: boolean) => void;
}) {
  return (
    <div>
      <p className="mb-1.5 text-sm font-medium text-foreground">{label}</p>
      <div className="flex gap-2" role="group" aria-label={label}>
        {[true, false].map((option) => (
          <Button
            key={String(option)}
            type="button"
            size="sm"
            variant={value === option ? "primary" : "outline"}
            aria-pressed={value === option}
            onClick={() => onChange(option)}
          >
            {option ? "Tak" : "Nie"}
          </Button>
        ))}
      </div>
    </div>
  );
}

interface EditDialogProps {
  details: ContractAdminDetails;
  clientName: string | null;
  onClose: () => void;
}

function EditDialog({ details, clientName, onClose }: EditDialogProps) {
  const { showToast } = useToast();
  const save = useSaveContractAdminDetails(details.contract_id);
  const [isReplacement, setIsReplacement] = useState<boolean | null>(
    details.is_replacement,
  );
  const [replaced, setReplaced] = useState<B2BReplaceableContract | null>(
    details.replaced,
  );
  const [isClientReferral, setIsClientReferral] = useState<boolean | null>(
    details.is_client_referral,
  );
  const [reason, setReason] = useState("");
  const [tried, setTried] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const missingPerson = isReplacement === true && replaced === null;
  const missingReason = reason.trim().length < 3;

  const submit = () => {
    setTried(true);
    setError(null);
    if (missingPerson || missingReason) return;
    save.mutate(
      {
        is_replacement: isReplacement,
        replaced_contract_id: isReplacement ? (replaced?.contract_id ?? null) : null,
        is_client_referral: isClientReferral,
        reason: reason.trim(),
      },
      {
        onSuccess: (result) => {
          showToast(
            result.changed.length
              ? "Zapisano. Premie kontraktu przeliczone."
              : "Bez zmian.",
            "success",
          );
          onClose();
        },
        onError: (err) =>
          setError(apiErrorMessage(err, "Nie udało się zapisać szczegółów.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(value) => {
        if (!value) onClose();
      }}
      title="Szczegóły administracyjne kontraktu"
      description="Od tych pól zależą premie z placementu. Zapis przelicza je od razu."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Wróć
          </Button>
          <Button onClick={submit} disabled={save.isPending}>
            {save.isPending ? "Zapisywanie…" : "Zapisz"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <YesNoField
          label="Replacement / gwarancja"
          value={isReplacement}
          onChange={(value) => {
            setIsReplacement(value);
            if (!value) setReplaced(null);
          }}
        />
        {isReplacement ? (
          <div>
            <p className="mb-1.5 text-sm font-medium text-foreground">
              Replacement / gwarancja za kogo
            </p>
            <ReplacedPicker
              candidateId={details.candidate_id}
              clientId={details.client_id}
              clientName={clientName}
              value={replaced}
              onChange={setReplaced}
              invalid={tried && missingPerson}
            />
            {tried && missingPerson ? (
              <p className="mt-1 text-xs text-destructive">
                Wskaż osobę, którą zastępuje.
              </p>
            ) : null}
          </div>
        ) : null}
        <YesNoField
          label="Kandydat wskazany przez klienta"
          value={isClientReferral}
          onChange={setIsClientReferral}
        />
        {isClientReferral ? (
          <p className="text-xs text-warning-muted-foreground">
            Bez premii z placementu: ani rekruter, ani Delivery Lead jej nie
            dostaną, a kontrakt nie liczy się do premii 200%.
          </p>
        ) : null}
        <FormField
          label="Powód zmiany"
          htmlFor="contract-admin-reason"
          error={tried && missingReason ? "Podaj powód zmiany." : undefined}
        >
          <Input
            id="contract-admin-reason"
            value={reason}
            maxLength={500}
            placeholder="np. zastępstwo potwierdzone przez Delivery"
            onChange={(event) => setReason(event.target.value)}
          />
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

/**
 * Kafelek nad „Premiami z tego kontraktu”. Widzą go Płace i osoby z prawem
 * oznaczania podpisu umów B2B (ta sama bramka co trasa); awaria zapytania to
 * komunikat, nie pusty kafelek.
 */
export function ContractAdminDetailsCard({
  contractId,
  clientName,
}: {
  contractId: number;
  clientName: string | null;
}) {
  const config = useHrConfig(true);
  const user = useAuthStore((s) => s.user);
  const allowed = Boolean(
    config.data?.open_modules.payroll &&
      (config.data?.me.payroll || hasPermission(user, "b2b_signature_confirmation")),
  );
  const query = useContractAdminDetails(contractId, allowed);
  const [editing, setEditing] = useState(false);
  if (!allowed) return null;
  if (query.isError) {
    return (
      <p
        role="alert"
        className="rounded-lg border border-border bg-card px-4 py-3 text-sm text-destructive"
      >
        Nie udało się wczytać szczegółów administracyjnych kontraktu.
      </p>
    );
  }
  if (!query.isSuccess) return null;
  const details = query.data;
  return (
    <section
      aria-label="Szczegóły administracyjne"
      className="rounded-lg border border-border bg-card px-4 py-3"
      data-tour="contract.admin-details"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <ClipboardList className="h-4 w-4" aria-hidden /> Szczegóły
          administracyjne
        </h2>
        <button
          type="button"
          className="text-sm font-medium text-primary hover:underline"
          onClick={() => setEditing(true)}
        >
          Zmień
        </button>
      </div>
      <dl className="mt-2 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        <div className="flex gap-2">
          <dt className="text-muted-foreground">Replacement / gwarancja:</dt>
          <dd className="text-foreground">
            {yesNo(details.is_replacement)}
            {details.is_replacement && details.replaced
              ? ` · za ${details.replaced.name} (kontrakt #${details.replaced.contract_id})`
              : ""}
          </dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-muted-foreground">Kandydat wskazany przez klienta:</dt>
          <dd className="text-foreground">
            {yesNo(details.is_client_referral)}
            {details.is_client_referral ? " · bez premii z placementu" : ""}
          </dd>
        </div>
      </dl>
      {editing ? (
        <EditDialog
          details={details}
          clientName={clientName}
          onClose={() => setEditing(false)}
        />
      ) : null}
    </section>
  );
}
