"use client";

// Opis faktury do księgowania wg „Ogólnych założeń” głównej księgowej
// (18.11.2026): typ, rejestr, konta netto / VAT / „5”, samochód, import usług,
// procedura JPK, kurs NBP i data zakończenia usługi. Dekret liczy serwer
// (`services/finance_ledger/posting.py`); puste pole = podpowiedź z reguły.

import { useState, type ReactNode } from "react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useChoiceLists,
  useDescriptionSave,
  type ChoiceOption,
  type DecreeSection,
} from "@/lib/api/finance-posting";

import {
  dayLabel,
  descriptionDraft,
  descriptionProblems,
  descriptionToInput,
  selfAssessed,
  type DescriptionDraft,
} from "./posting-model";

const CONTROL =
  "h-8 w-full min-w-0 rounded-md border border-border bg-background px-2 text-sm pointer-coarse:h-10";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="grid gap-0.5 text-xs text-muted-foreground">
      <span>{label}</span>
      {children}
    </label>
  );
}

function Select({
  label,
  value,
  options,
  hint,
  onChange,
}: {
  label: string;
  value: string;
  options: ChoiceOption[];
  hint: string | null | undefined;
  onChange: (value: string) => void;
}) {
  return (
    <Field label={label}>
      <select
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={CONTROL}
      >
        <option value="">{hint ? `z reguły: ${hint}` : "—"}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
            {option.in_plan === false ? " (brak w planie)" : ""}
          </option>
        ))}
      </select>
    </Field>
  );
}

function AccountInput({
  label,
  value,
  options,
  hint,
  listId,
  onChange,
}: {
  label: string;
  value: string;
  options: ChoiceOption[];
  hint: string | null | undefined;
  listId: string;
  onChange: (value: string) => void;
}) {
  return (
    <Field label={label}>
      <Input
        aria-label={label}
        list={listId}
        value={value}
        placeholder={hint ? `z reguły: ${hint}` : "wybierz z listy"}
        onChange={(event) => onChange(event.target.value)}
        className="h-8 font-mono text-[12.5px]"
      />
      <datalist id={listId}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </datalist>
    </Field>
  );
}

function Check({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-1.5 text-sm">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="size-4 accent-primary"
      />
      {label}
    </label>
  );
}

function YesNo({
  label,
  value,
  hint,
  onChange,
}: {
  label: string;
  value: "" | "yes" | "no";
  hint: string;
  onChange: (value: "" | "yes" | "no") => void;
}) {
  return (
    <Field label={label}>
      <select
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value as "" | "yes" | "no")}
        className={CONTROL}
      >
        <option value="">{`podpowiedź: ${hint}`}</option>
        <option value="yes">tak</option>
        <option value="no">nie</option>
      </select>
    </Field>
  );
}

/** Formularz opisu; zapis liczy dekret od nowa z reguły i wyborów. */
export function DescriptionForm({
  entryId,
  section,
  onDone,
}: {
  entryId: number;
  section: DecreeSection;
  onDone: () => void;
}) {
  const [draft, setDraft] = useState<DescriptionDraft>(() => descriptionDraft(section));
  const lists = useChoiceLists();
  const save = useDescriptionSave(entryId);
  const { showToast } = useToast();
  const effective = section.effective ?? null;
  const set = <K extends keyof DescriptionDraft>(key: K, value: DescriptionDraft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));
  const assessed = selfAssessed(draft, effective?.doc_type ?? null);
  const foreign = Boolean(section.currency && section.currency !== "PLN");
  const problems = descriptionProblems(draft);
  const data = lists.data;
  if (lists.isError) {
    return (
      <p className="text-sm text-destructive">
        {apiErrorMessage(lists.error, "Nie udało się pobrać list kont do opisu.")}
      </p>
    );
  }
  return (
    <div className="space-y-3" aria-label="Opis do księgowania">
      <Field label="Opis księgowy">
        <Input
          aria-label="Opis księgowy"
          value={draft.description}
          maxLength={255}
          placeholder={effective?.description || "np. Usługi IT 10/2026"}
          onChange={(event) => set("description", event.target.value)}
          className="h-8"
        />
      </Field>
      <div className="grid grid-cols-2 gap-2">
        <Select
          label="Typ dokumentu"
          value={draft.doc_type}
          options={data?.doc_types ?? []}
          hint={effective?.doc_type}
          onChange={(value) => set("doc_type", value)}
        />
        <Select
          label="Rejestr"
          value={draft.register}
          options={data?.registers ?? []}
          hint={effective?.register}
          onChange={(value) => set("register", value)}
        />
        <AccountInput
          label="Konto netto (zespół 4 i 7)"
          value={draft.net_account}
          options={data?.net_accounts ?? []}
          hint={effective?.net_account}
          listId={`net-accounts-${entryId}`}
          onChange={(value) => set("net_account", value)}
        />
        <Select
          label="Konto VAT"
          value={draft.vat_account}
          options={data?.vat_accounts ?? []}
          hint={effective?.vat_account}
          onChange={(value) => set("vat_account", value)}
        />
        <AccountInput
          label={`Konto „5” (Wn 5 / Ma ${data?.allocation_offset ?? "490"})`}
          value={draft.allocation_account}
          options={data?.allocation_accounts ?? []}
          hint={null}
          listId={`allocation-accounts-${entryId}`}
          onChange={(value) => set("allocation_account", value)}
        />
        <Select
          label="Procedura JPK"
          value={draft.jpk_procedure}
          options={data?.jpk_procedures ?? []}
          hint={effective?.jpk_procedure}
          onChange={(value) => set("jpk_procedure", value)}
        />
        <Field label="Data zakończenia dostawy / usługi">
          <Input
            type="date"
            aria-label="Data zakończenia dostawy / usługi"
            value={draft.service_date}
            onChange={(event) => set("service_date", event.target.value)}
            className="h-8"
          />
        </Field>
      </div>
      {draft.allocation_account ? (
        <Button size="sm" variant="ghost" onClick={() => set("allocation_account", "")}>
          Usuń linię „5” z dekretu
        </Button>
      ) : null}
      <div className="space-y-2 rounded-md border border-border p-2.5">
        <Check
          label="Paliwo i leasingi (samochód: netto + ½ VAT, rejestr w dwóch połowach)"
          checked={draft.car}
          onChange={(value) => set("car", value)}
        />
        {draft.car ? (
          <Select
            label={`Pozabilansowo ½ brutto: Wn ${data?.offbalance_debit ?? "999"} / Ma`}
            value={draft.offbalance_account}
            options={data?.offbalance_accounts ?? []}
            hint={null}
            onChange={(value) => set("offbalance_account", value)}
          />
        ) : null}
      </div>
      <div className="space-y-2 rounded-md border border-border p-2.5">
        <Check
          label="Rejestr VAT należnego (import usług, WNT, odwrotne obciążenie)"
          checked={draft.output || assessed}
          onChange={(value) => set("output", value)}
        />
        {assessed ? (
          <div className="grid grid-cols-2 gap-2">
            <Select
              label="Rejestr VAT należnego"
              value={draft.output_register}
              options={data?.output_registers ?? []}
              hint={effective?.output_register}
              onChange={(value) => set("output_register", value)}
            />
            <Select
              label="Konto VAT należnego"
              value={draft.output_vat_account}
              options={data?.output_vat_accounts ?? []}
              hint={effective?.output_vat_account}
              onChange={(value) => set("output_vat_account", value)}
            />
            <YesNo
              label="UE"
              value={draft.eu}
              hint={
                section.self_assessed
                  ? effective?.eu
                    ? "tak"
                    : "nie"
                  : "kontrahent z VAT UE"
              }
              onChange={(value) => set("eu", value)}
            />
            <YesNo
              label="Usługa"
              value={draft.service}
              hint={(draft.doc_type || effective?.doc_type) === "WNT" ? "nie (WNT)" : "tak"}
              onChange={(value) => set("service", value)}
            />
            <Field label="Stawka VAT">
              <select
                aria-label="Stawka VAT"
                value={draft.import_rate}
                onChange={(event) => set("import_rate", event.target.value)}
                className={CONTROL}
              >
                <option value="">23% (domyślnie)</option>
                {(data?.import_rates ?? []).map((rate) => (
                  <option key={rate} value={String(rate)}>
                    {rate}%
                  </option>
                ))}
              </select>
            </Field>
          </div>
        ) : null}
      </div>
      {foreign ? (
        <div className="grid grid-cols-3 gap-2 rounded-md border border-border p-2.5">
          <Field label="Data kursu">
            <Input
              type="date"
              aria-label="Data kursu"
              value={draft.fx_date}
              onChange={(event) => set("fx_date", event.target.value)}
              className="h-8"
            />
          </Field>
          <Field label={`Kurs ${section.currency}`}>
            <Input
              aria-label="Kurs"
              inputMode="decimal"
              value={draft.fx_rate}
              placeholder={effective?.fx_rate ?? "z tabeli NBP"}
              onChange={(event) => set("fx_rate", event.target.value)}
              className="h-8 tabular-nums"
            />
          </Field>
          <Field label="Tabela NBP">
            <Input
              aria-label="Tabela NBP"
              value={draft.fx_table}
              placeholder="np. 211/A/NBP/2026"
              onChange={(event) => set("fx_table", event.target.value)}
              className="h-8 font-mono text-[12.5px]"
            />
          </Field>
        </div>
      ) : null}
      {problems.length > 0 ? (
        <ul className="space-y-0.5 text-xs text-destructive" aria-label="Do poprawy w opisie">
          {problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      ) : null}
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={onDone}>
          Anuluj
        </Button>
        <Button
          size="sm"
          disabled={problems.length > 0}
          loading={save.isPending}
          onClick={() =>
            save.mutate(descriptionToInput(draft, effective?.doc_type ?? null), {
              onSuccess: () => {
                showToast("Opis zapisany, dekret przeliczony.", "success");
                onDone();
              },
              onError: (err) =>
                showToast(apiErrorMessage(err, "Nie udało się zapisać opisu."), "error"),
            })
          }
        >
          Zapisz opis
        </Button>
      </div>
    </div>
  );
}

/** Rejestry VAT i atrybuty z opisu (widok karty). */
export function DescriptionSummary({ section }: { section: DecreeSection }) {
  const registers = section.registers ?? [];
  return (
    <>
      {registers.length > 0 ? (
        <>
          <dt className="text-muted-foreground">Rejestr VAT</dt>
          <dd>
            <ul className="space-y-0.5">
              {registers.map((item, index) => (
                <li key={`${item.name}-${index}`} className="tabular-nums">
                  {item.name} · {item.rate ?? "—"}% · netto {item.net.replace(".", ",")} · VAT{" "}
                  {item.vat.replace(".", ",")}
                  {item.output ? " · należny" : ""}
                  {item.eu ? " · UE" : ""}
                  {item.service ? " · usługa" : ""}
                </li>
              ))}
            </ul>
          </dd>
        </>
      ) : null}
      {section.jpk_procedure ? (
        <>
          <dt className="text-muted-foreground">Procedura JPK</dt>
          <dd>{section.jpk_procedure}</dd>
        </>
      ) : null}
      {section.service_date ? (
        <>
          <dt className="text-muted-foreground">Zakończenie usługi</dt>
          <dd>{dayLabel(section.service_date)}</dd>
        </>
      ) : null}
      {section.car ? (
        <>
          <dt className="text-muted-foreground">Samochód</dt>
          <dd>netto + ½ VAT w koszt, ½ VAT do odliczenia</dd>
        </>
      ) : null}
    </>
  );
}
