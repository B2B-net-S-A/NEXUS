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
import {
  useCreateBonus,
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
}: BonusDialogProps) {
  const { showToast } = useToast();
  const create = useCreateBonus();
  const update = useUpdateBonus();
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
  const pending = create.isPending || update.isPending;
  const categories = bonus && !MANUAL_CATEGORIES.includes(bonus.category)
    ? [...MANUAL_CATEGORIES, bonus.category]
    : MANUAL_CATEGORIES;

  const submit = () => {
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
    if (bonus) {
      update.mutate(
        { id: bonus.id, patch: fields },
        {
          onSuccess: () => {
            showToast("Premia zmieniona", "success");
            onOpenChange(false);
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
      { ...fields, recipient_user_id: Number(personId) },
      {
        onSuccess: (created) => {
          showToast(bonusCreatedToast(created), "success");
          onOpenChange(false);
        },
        onError,
      },
    );
  };

  const recipientName =
    fixedPerson?.name ?? bonus?.recipient_name ?? people.find((p) => String(p.user_id) === personId)?.name;

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={bonus ? "Zmień premię" : "Nowa premia"}
      description={
        bonus || fixedPerson
          ? recipientName ?? undefined
          : "Osoba dostanie powiadomienie bez kwoty — kwotę zobaczy w „Moim czasie”."
      }
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={pending}>
            {pending ? "Zapisywanie…" : bonus ? "Zapisz zmiany" : "Przyznaj premię"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {!bonus && !fixedPerson ? (
          <FormField label="Osoba" htmlFor="bonus-person" className="sm:col-span-2">
            <Select value={personId} onValueChange={setPersonId}>
              <SelectTrigger id="bonus-person">
                <SelectValue placeholder="Wybierz osobę" />
              </SelectTrigger>
              <SelectContent>
                {people.map((person) => (
                  <SelectItem key={person.user_id} value={String(person.user_id)}>
                    {person.name}
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
          description="Ostatnie 12 miesięcy albo bieżący."
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
