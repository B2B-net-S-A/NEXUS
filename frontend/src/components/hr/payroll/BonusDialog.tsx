"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage } from "@/lib/api-error";
import { usePeople } from "@/lib/api/hr";
import {
  useApproveBonus,
  useCreateBonus,
  usePlacementOptions,
  useUpdateBonus,
  type BonusCategory,
  type BonusRow,
  type Currency,
} from "@/lib/api/hr-payroll";

import {
  bonusCreatedToast,
  CATEGORY_LABELS,
  CURRENCIES,
  MANUAL_CATEGORIES,
  parseAmount,
  warsawMonth,
  ymSegment,
} from "./payroll-format";

const NO_PLACEMENT = "none";

export interface BonusPerson {
  user_id: number;
  name: string;
}

interface BonusDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Osoby, którym można przyznać premię (Płace: lista miesiąca; przełożony: zespół). */
  people: BonusPerson[];
  /** Osoba ustalona z góry (kartoteka) — bez listy wyboru. */
  fixedPerson?: BonusPerson;
  /** Miesiąc premii na start („RRRR-MM”). */
  defaultMonth?: string;
  /** Edycja istniejącej premii (kwota, waluta, kategoria, miesiąc, opis). */
  bonus?: BonusRow;
  /** Płace: zmiana osoby i placementu, „Zapisz i zatwierdź”, „Usuń premię”. */
  fullEdit?: boolean;
  /** Usunięcie premii: okno zamyka się, a potwierdzenie z powodem robi ekran. */
  onDelete?: (row: BonusRow) => void;
}

/** Skąd kwota: słowa z migawki automatu (tylko Płace). */
export function bonusCalculation(bonus: BonusRow): string | null {
  const snapshot = bonus.rule_snapshot;
  const margin = snapshot?.margin_per_hour;
  if (!margin) return null;
  const marginLabel = `Marża ${String(margin).replace(".", ",")} zł/h`;
  if (snapshot?.individual_percent) {
    return `${marginLabel}, ${String(snapshot.individual_percent).replace(".", ",")}% marży miesięcznej (starty w miesiącu: ${String(snapshot.recruiter_starts)}).`;
  }
  if (snapshot?.role === "recruiter") return `${marginLabel}, próg ${String(snapshot.tier)}.`;
  const hours = snapshot?.dl_hours ?? snapshot?.monthly_hours;
  return `${String(snapshot?.dl_percent ?? "10").replace(".", ",")}% × ${String(margin).replace(".", ",")} zł/h × ${String(hours)} h.`;
}

/**
 * Premia ręczna (Płace albo przełożony swojemu człowiekowi) i zmiana premii.
 * Kwota trafia tylko do Płac i osoby; dzwonek do osoby nie niesie kwoty.
 */
export function BonusDialog({
  open,
  onOpenChange,
  people,
  fixedPerson,
  defaultMonth,
  bonus,
  fullEdit = false,
  onDelete,
}: BonusDialogProps) {
  const { showToast } = useToast();
  const create = useCreateBonus();
  const update = useUpdateBonus();
  const approve = useApproveBonus();
  // Karta na kontrakcie nie zna listy miesiąca: osoby z kartoteki.
  const directory = usePeople(fullEdit && people.length === 0);
  const canPickPlacement = fullEdit || (!bonus && !fixedPerson);
  const automated = bonus ? bonus.source !== "manual" : false;
  const placements = usePlacementOptions(canPickPlacement && !automated);
  const [contractId, setContractId] = useState(bonus?.contract_id ? String(bonus.contract_id) : NO_PLACEMENT);
  const [reason, setReason] = useState("");
  const [personId, setPersonId] = useState(
    fixedPerson ? String(fixedPerson.user_id) : bonus ? String(bonus.recipient_user_id) : "",
  );
  const [amount, setAmount] = useState(bonus ? bonus.amount.replace(".", ",") : "");
  const [currency, setCurrency] = useState<Currency>(bonus?.currency ?? "PLN");
  const [category, setCategory] = useState<BonusCategory>(bonus?.category ?? "custom");
  const [month, setMonth] = useState(
    bonus ? ymSegment(bonus.period_year, bonus.period_month) : defaultMonth ?? warsawMonth(),
  );
  const [description, setDescription] = useState(bonus?.description ?? "");
  const [error, setError] = useState<string | null>(null);
  const pending = create.isPending || update.isPending || approve.isPending;
  const personChanged = bonus !== undefined && personId !== String(bonus.recipient_user_id);
  const categories = bonus && !MANUAL_CATEGORIES.includes(bonus.category)
    ? [...MANUAL_CATEGORIES, bonus.category]
    : MANUAL_CATEGORIES;

  const submit = (thenApprove = false) => {
    setError(null);
    const value = parseAmount(amount);
    if (!value || Number(value) <= 0) {
      setError("Podaj kwotę większą od zera, np. 1500 albo 772,80.");
      return;
    }
    const [year, monthNumber] = month.split("-").map(Number);
    if (!year || !monthNumber) {
      setError("Wybierz miesiąc premii.");
      return;
    }
    const fields = {
      amount: value,
      currency,
      category,
      period_year: year,
      period_month: monthNumber,
      description: description.trim() || null,
    };
    const onError = (err: unknown) => setError(apiErrorMessage(err, "Nie udało się zapisać premii."));
    const placement = contractId === NO_PLACEMENT ? null : Number(contractId);
    if (bonus) {
      if (personChanged && !reason.trim()) {
        setError("Podaj powód zmiany osoby.");
        return;
      }
      const patch = {
        ...fields,
        ...(personChanged ? { recipient_user_id: Number(personId), change_reason: reason.trim() } : {}),
        ...(fullEdit && !automated ? { contract_id: placement } : {}),
      };
      update.mutate(
        { id: bonus.id, patch },
        {
          onSuccess: () => {
            if (!thenApprove) {
              showToast("Premia zmieniona", "success");
              onOpenChange(false);
              return;
            }
            approve.mutate(bonus.id, {
              onSuccess: () => {
                showToast("Premia zapisana i zatwierdzona", "success");
                onOpenChange(false);
              },
              onError,
            });
          },
          onError,
        },
      );
      return;
    }
    if (!personId) {
      setError("Wybierz osobę.");
      return;
    }
    create.mutate(
      { ...fields, recipient_user_id: Number(personId), contract_id: placement },
      {
        onSuccess: (created) => {
          showToast(bonusCreatedToast(created), "success");
          onOpenChange(false);
        },
        onError,
      },
    );
  };

  // Obecny odbiorca zostaje na liście, także gdy nie pracuje w tym miesiącu.
  const roster = people.length > 0 ? people : (directory.data?.items ?? []);
  const pickable =
    bonus && !roster.some((person) => person.user_id === bonus.recipient_user_id)
      ? [...roster, { user_id: bonus.recipient_user_id, name: bonus.recipient_name ?? "Obecna osoba" }]
      : roster;


  const recipientName =
    fixedPerson?.name ?? bonus?.recipient_name ?? people.find((p) => String(p.user_id) === personId)?.name;

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={bonus ? "Zmień premię" : "Nowa premia"}
      description={
        fullEdit && bonus?.description
          ? bonus.description
          : bonus || fixedPerson
            ? recipientName ?? undefined
          : "Osoba dostanie powiadomienie bez kwoty — kwotę zobaczy w „Moim czasie”."
      }
      footer={
        <>
          {fullEdit && bonus && onDelete ? (
            <Button variant="ghost" className="mr-auto text-destructive" onClick={() => onDelete(bonus)}>
              Usuń premię
            </Button>
          ) : null}
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          {fullEdit && bonus?.status === "proposed" ? (
            <>
              <Button variant="secondary" onClick={() => submit()} disabled={pending}>
                Zapisz
              </Button>
              <Button onClick={() => submit(true)} disabled={pending}>
                {pending ? "Zapisywanie…" : "Zapisz i zatwierdź"}
              </Button>
            </>
          ) : (
            <Button onClick={() => submit()} disabled={pending}>
              {pending ? "Zapisywanie…" : bonus ? "Zapisz zmiany" : "Przyznaj premię"}
            </Button>
          )}
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {bonus?.flags?.length ? (
          <ul className="space-y-1 rounded-lg bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground sm:col-span-2">
            {bonus.flags.map((flag) => (
              <li key={flag.code}>
                <strong>{flag.label}:</strong> {flag.detail}
              </li>
            ))}
          </ul>
        ) : null}
        {bonus && fullEdit && bonusCalculation(bonus) ? (
          <p className="rounded-lg bg-muted/50 px-3 py-2 text-sm text-foreground sm:col-span-2">
            <strong>Jak policzone:</strong> {bonusCalculation(bonus)}
          </p>
        ) : null}
        {(!bonus && !fixedPerson) || (bonus && fullEdit) ? (
          <FormField label="Osoba" htmlFor="bonus-person" className="sm:col-span-2">
            <Select value={personId} onValueChange={setPersonId}>
              <SelectTrigger id="bonus-person">
                <SelectValue placeholder="Wybierz osobę" />
              </SelectTrigger>
              <SelectContent>
                {pickable.map((person) => (
                  <SelectItem key={person.user_id} value={String(person.user_id)}>
                    {person.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        ) : null}
        {personChanged ? (
          <FormField label="Powód zmiany osoby" htmlFor="bonus-reason" className="sm:col-span-2">
            <Input
              id="bonus-reason"
              value={reason}
              maxLength={1000}
              onChange={(event) => setReason(event.target.value)}
            />
          </FormField>
        ) : null}
        {canPickPlacement && !automated ? (
          <FormField label="Za kogo (placement)" htmlFor="bonus-placement" className="sm:col-span-2">
            <Select value={contractId} onValueChange={setContractId}>
              <SelectTrigger id="bonus-placement">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_PLACEMENT}>Bez placementu</SelectItem>
                {(placements.data ?? []).map((option) => (
                  <SelectItem key={option.contract_id} value={String(option.contract_id)}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        ) : null}
        <FormField label="Kwota" htmlFor="bonus-amount">
          <Input
            id="bonus-amount"
            inputMode="decimal"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
          />
        </FormField>
        <FormField label="Waluta" htmlFor="bonus-currency">
          <Select value={currency} onValueChange={(value) => setCurrency(value as Currency)}>
            <SelectTrigger id="bonus-currency">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CURRENCIES.map((code) => (
                <SelectItem key={code} value={code}>
                  {code}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="Kategoria" htmlFor="bonus-category">
          <Select value={category} onValueChange={(value) => setCategory(value as BonusCategory)}>
            <SelectTrigger id="bonus-category">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {categories.map((key) => (
                <SelectItem key={key} value={key}>
                  {CATEGORY_LABELS[key]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField
          label="Miesiąc wypłaty"
          htmlFor="bonus-month"
          description={fullEdit ? undefined : "Ostatnie 12 miesięcy albo bieżący."}
        >
          <Input
            id="bonus-month"
            type="month"
            value={month}
            onChange={(event) => setMonth(event.target.value)}
          />
        </FormField>
        <FormField label="Za co" htmlFor="bonus-description" className="sm:col-span-2">
          <Input
            id="bonus-description"
            value={description}
            maxLength={1000}
            onChange={(event) => setDescription(event.target.value)}
          />
        </FormField>
      </div>
      {error ? (
        <p role="alert" className="mt-4 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}
