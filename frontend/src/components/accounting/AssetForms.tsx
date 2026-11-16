"use client";

import { useEffect, useState, type ChangeEvent, type ReactNode } from "react";

import { AppModal } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  useAddAssetOperation,
  useAssetsImport,
  useCostEntryOptions,
  useCreateAsset,
  useEquipmentOptions,
  useSetAssetsAccounts,
  useUpdateAsset,
  type AssetCard,
  type AssetImportResult,
  type AssetKind,
  type AssetMethod,
  type AssetOperationType,
  type AssetsAccounts,
  type CostEntryOption,
  type EquipmentOption,
} from "@/lib/api/accounting-assets";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { useAccounting } from "./AccountingShell";
import {
  DEFAULT_ACCOUNTS,
  METHOD_LABELS,
  MPK_OPTIONS,
  assetBody,
  emptyAssetForm,
  monthText,
  type AssetFormValues,
} from "./assets-model";
import { datePl, gr, parseAmount, shiftPeriod } from "./ledger-model";

const CONTROL = "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";
const METHODS = Object.keys(METHOD_LABELS) as AssetMethod[];
const OPERATION_TITLES: Record<Exclude<AssetOperationType, "OT">, string> = {
  UL: "Ulepszenie — zwiększenie wartości",
  MT: "Zmiana MPK (MT)",
  LT: "Likwidacja (LT)",
  SP: "Sprzedaż",
};
const OPERATION_HINTS: Record<Exclude<AssetOperationType, "OT">, string> = {
  UL: "Wartość początkowa rośnie od dnia dokumentu, odpis od następnego miesiąca. Zapis: Wn konto środka / Ma konto przeciwstawne.",
  MT: "Bez zapisu w księdze — AM dzieli odpis na nowe MPK od miesiąca dokumentu.",
  LT: "Odpis za miesiąc likwidacji zostaje, potem żadnego. Zapis: Wn umorzenie i wartość netto (pozostałe koszty) / Ma środek.",
  SP: "Odpis za miesiąc sprzedaży zostaje. Zapis zdejmuje środek jak likwidacja; przychód księguje faktura sprzedaży.",
};

function Field({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <label className={cn("flex min-w-0 flex-col gap-1 text-[12px] text-muted-foreground", className)}>
      {label}
      {children}
    </label>
  );
}

function toInput(grosze: number | null | undefined): string {
  if (grosze == null) return "";
  return gr(grosze).replace(/\s/g, "");
}

function formFromCard(card: AssetCard): AssetFormValues {
  const intake = card.operations.find((op) => op.op_type === "OT");
  return {
    ...emptyAssetForm(card.accepted_on, intake?.counter_account ?? ""),
    name: card.name,
    kind: card.kind,
    kst: card.kst ?? "",
    inventoryNumber: card.inventory_number,
    initialValue: toInput(card.initial_value),
    assetAccount: card.asset_account,
    depreciationAccount: card.depreciation_account,
    mpk: card.mpk,
    balanceMethod: card.balance_method,
    balanceRate: card.balance_rate,
    taxMethod: card.tax_method,
    taxRate: card.tax_rate,
    coefficient: card.coefficient.replace(".", ","),
    note: card.note,
    equipmentItemId: card.equipment?.id ?? null,
    costEntryId: intake?.cost_entry?.id ?? null,
    postIntake: intake ? intake.counter_account != null : true,
    counterAccount: intake?.counter_account ?? "",
    fromSymfonia: card.opening != null,
    openingMonth: card.opening?.month ?? card.accepted_on.slice(0, 7),
    openingBalance: toInput(card.opening?.balance ?? 0),
    openingTax: toInput(card.opening?.tax),
    openingBalanceYear: toInput(card.opening?.balance_year),
    openingTaxYear: toInput(card.opening?.tax_year),
  };
}

/** Przyjęcie środka (OT) albo poprawka karty. Zablokowany plan = tylko opis. */
export function AssetFormModal({
  open,
  editing,
  intakeAccount,
  onClose,
  onSaved,
}: {
  open: boolean;
  editing: AssetCard | null;
  intakeAccount: string;
  onClose: () => void;
  onSaved?: (id: number) => void;
}) {
  const { config } = useAccounting();
  const { showToast } = useToast();
  const create = useCreateAsset();
  const update = useUpdateAsset();
  const [values, setValues] = useState<AssetFormValues>(() => emptyAssetForm(config.today, intakeAccount));
  const [equipment, setEquipment] = useState<EquipmentOption | null>(null);
  const [invoice, setInvoice] = useState<CostEntryOption | null>(null);
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    if (!open) return;
    setTouched(false);
    setValues(editing ? formFromCard(editing) : emptyAssetForm(config.today, intakeAccount));
    setEquipment(editing?.equipment ?? null);
    setInvoice(editing?.operations.find((op) => op.op_type === "OT")?.cost_entry ?? null);
  }, [open, editing, config.today, intakeAccount]);

  const locked = editing?.locked != null;
  const { body, problems } = assetBody(values, { planLocked: locked });
  const set =
    <K extends keyof AssetFormValues>(key: K) =>
    (event: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
      setValues((current) => ({ ...current, [key]: event.target.value as AssetFormValues[K] }));
  const setKind = (kind: AssetKind) =>
    setValues((current) => ({
      ...current,
      kind,
      assetAccount: DEFAULT_ACCOUNTS[kind].asset,
      depreciationAccount: DEFAULT_ACCOUNTS[kind].depreciation,
      taxMethod: kind === "intangible" && current.taxMethod === "degressive" ? "linear" : current.taxMethod,
    }));
  const pickInvoice = (item: CostEntryOption) => {
    setInvoice(item);
    setValues((current) => ({
      ...current,
      costEntryId: item.id,
      initialValue: current.initialValue || (item.currency === "PLN" && item.net_amount ? toInput(item.net_amount) : ""),
      acceptedOn: item.issue_date ?? current.acceptedOn,
      note: current.note || `Faktura ${item.invoice_number ?? ""} — ${item.seller_name ?? ""}`.trim(),
    }));
  };
  const pickEquipment = (item: EquipmentOption | null) => {
    setEquipment(item);
    setValues((current) => ({
      ...current,
      equipmentItemId: item?.id ?? null,
      name: current.name || (item ? item.model : ""),
    }));
  };

  const submit = () => {
    setTouched(true);
    if (problems.length) return;
    const done = (message: string) => {
      showToast(message);
      onClose();
    };
    const failed = (error: unknown) => showToast(apiErrorMessage(error, "Nie udało się zapisać środka."), "error");
    if (editing) {
      update.mutate({ id: editing.id, body }, { onSuccess: () => done(`Zapisano ${editing.inventory_number}.`), onError: failed });
    } else {
      create.mutate(body, {
        onSuccess: (result) => {
          onSaved?.(result.id);
          done(`Przyjęto ${result.inventory_number}.`);
        },
        onError: failed,
      });
    }
  };

  return (
    <AppModal
      open={open}
      onOpenChange={(next) => (next ? null : onClose())}
      size="xl"
      title={editing ? `Karta środka ${editing.inventory_number}` : "Przyjęcie środka (OT)"}
      description={
        locked
          ? "Środek ma zatwierdzony zapis — zmienisz tylko opis. Wartość i plan poprawia dokument (ulepszenie, likwidacja) albo storno."
          : "Odpisy od miesiąca po przyjęciu. Plan bilansowy idzie do księgi (AM), podatkowy do CIT."
      }
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button loading={create.isPending || update.isPending} onClick={submit}>
            {editing ? "Zapisz kartę" : "Przyjmij środek"}
          </Button>
        </>
      }
    >
      <div className="space-y-3.5 text-sm">
        <div className="grid gap-3 sm:grid-cols-4">
          <Field label="Nazwa" className="sm:col-span-2">
            <input className={CONTROL} value={values.name} onChange={set("name")} placeholder="np. Stacje robocze (3 szt.)" />
          </Field>
          <Field label="Rodzaj">
            <select
              className={CONTROL}
              value={values.kind}
              disabled={locked}
              onChange={(event) => setKind(event.target.value as AssetKind)}
            >
              <option value="fixed">Środek trwały</option>
              <option value="intangible">WNiP</option>
            </select>
          </Field>
          <Field label={values.kind === "fixed" ? "KŚT (2016)" : "KŚT — nie dotyczy WNiP"}>
            <input
              className={cn(CONTROL, "font-mono")}
              value={values.kind === "fixed" ? values.kst : ""}
              disabled={values.kind !== "fixed"}
              onChange={set("kst")}
              placeholder="np. 491"
            />
          </Field>
          <Field label="Numer inwentarzowy">
            <input
              className={cn(CONTROL, "font-mono")}
              value={values.inventoryNumber}
              onChange={set("inventoryNumber")}
              placeholder={editing ? "" : "kolejny, np. ST/2026/004"}
            />
          </Field>
          <Field label="Data przyjęcia">
            <input type="date" className={CONTROL} value={values.acceptedOn} disabled={locked} onChange={set("acceptedOn")} />
          </Field>
          <Field label="Wartość początkowa, zł">
            <input
              className={cn(CONTROL, "text-right tabular-nums")}
              value={values.initialValue}
              disabled={locked}
              onChange={set("initialValue")}
              inputMode="decimal"
              placeholder="0,00"
            />
          </Field>
          <Field label="MPK">
            <input
              className={cn(CONTROL, "uppercase")}
              list="asset-mpk-options"
              value={values.mpk}
              disabled={locked || editing?.operations.some((op) => op.op_type === "MT")}
              onChange={set("mpk")}
              placeholder="OG, FO, BO albo K<id klienta>"
            />
            <datalist id="asset-mpk-options">
              {MPK_OPTIONS.map((option) => (
                <option key={option.code} value={option.code}>
                  {option.label}
                </option>
              ))}
            </datalist>
          </Field>
        </div>

        <fieldset className="grid gap-3 rounded-md border border-border/70 p-3 sm:grid-cols-5" disabled={locked}>
          <legend className="px-1 text-[12px] font-medium text-foreground">Plan amortyzacji</legend>
          <Field label="Bilansowo — metoda">
            <select className={CONTROL} value={values.balanceMethod} onChange={set("balanceMethod")}>
              {METHODS.map((method) => (
                <option key={method} value={method}>
                  {METHOD_LABELS[method]}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Stawka bilansowa, %">
            <input className={cn(CONTROL, "tabular-nums")} value={values.balanceRate} onChange={set("balanceRate")} placeholder="np. 30" />
          </Field>
          <Field label="Podatkowo — metoda">
            <select className={CONTROL} value={values.taxMethod} onChange={set("taxMethod")}>
              {METHODS.filter((method) => values.kind === "fixed" || method !== "degressive").map((method) => (
                <option key={method} value={method}>
                  {METHOD_LABELS[method]}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Stawka podatkowa, %">
            <input
              className={cn(CONTROL, "tabular-nums")}
              value={values.taxRate}
              onChange={set("taxRate")}
              placeholder={values.balanceRate ? `jak bilansowa (${values.balanceRate})` : "np. 30"}
            />
          </Field>
          <Field label="Współczynnik degresywnej">
            <input
              className={cn(CONTROL, "tabular-nums")}
              value={values.coefficient}
              onChange={set("coefficient")}
              disabled={values.balanceMethod !== "degressive" && values.taxMethod !== "degressive"}
            />
          </Field>
          <Field label="Konto środka">
            <input className={cn(CONTROL, "font-mono")} value={values.assetAccount} onChange={set("assetAccount")} />
          </Field>
          <Field label="Konto umorzenia">
            <input className={cn(CONTROL, "font-mono")} value={values.depreciationAccount} onChange={set("depreciationAccount")} />
          </Field>
        </fieldset>

        {!editing ? (
          <div className="space-y-2 rounded-md border border-border/70 p-3">
            <label className="flex items-center gap-2 text-[13px]">
              <input
                type="checkbox"
                checked={values.fromSymfonia}
                onChange={(event) => setValues((current) => ({ ...current, fromSymfonia: event.target.checked }))}
              />
              Środek przyjęty wcześniej — wprowadzam stan umorzenia z Symfonii (bez OT w księdze)
            </label>
            {values.fromSymfonia ? (
              <div className="grid gap-3 sm:grid-cols-5">
                <Field label="Stan na koniec miesiąca">
                  <input type="month" className={CONTROL} value={values.openingMonth} onChange={set("openingMonth")} />
                </Field>
                <Field label="Umorzenie bilansowe, zł">
                  <input className={cn(CONTROL, "text-right tabular-nums")} value={values.openingBalance} onChange={set("openingBalance")} />
                </Field>
                <Field label="Umorzenie podatkowe, zł">
                  <input
                    className={cn(CONTROL, "text-right tabular-nums")}
                    value={values.openingTax}
                    onChange={set("openingTax")}
                    placeholder="jak bilansowe"
                  />
                </Field>
                {values.balanceMethod === "degressive" || values.taxMethod === "degressive" ? (
                  <>
                    <Field label="Bilansowe na początek roku">
                      <input
                        className={cn(CONTROL, "text-right tabular-nums")}
                        value={values.openingBalanceYear}
                        onChange={set("openingBalanceYear")}
                      />
                    </Field>
                    <Field label="Podatkowe na początek roku">
                      <input
                        className={cn(CONTROL, "text-right tabular-nums")}
                        value={values.openingTaxYear}
                        onChange={set("openingTaxYear")}
                        placeholder="jak bilansowe"
                      />
                    </Field>
                  </>
                ) : null}
              </div>
            ) : (
              <div className="grid gap-3 sm:grid-cols-[auto_10rem_minmax(0,1fr)] sm:items-end">
                <label className="flex items-center gap-2 text-[13px]">
                  <input
                    type="checkbox"
                    checked={values.postIntake}
                    onChange={(event) => setValues((current) => ({ ...current, postIntake: event.target.checked }))}
                  />
                  OT w księdze
                </label>
                <Field label="Konto przeciwstawne">
                  <input
                    className={cn(CONTROL, "font-mono")}
                    value={values.counterAccount}
                    disabled={!values.postIntake}
                    onChange={set("counterAccount")}
                  />
                </Field>
                <CostEntryPicker selected={invoice} onPick={pickInvoice} onClear={() => {
                  setInvoice(null);
                  setValues((current) => ({ ...current, costEntryId: null }));
                }} />
              </div>
            )}
          </div>
        ) : null}

        <div className="grid gap-3 sm:grid-cols-2">
          <EquipmentPicker selected={equipment} onPick={pickEquipment} />
          <Field label="Uwagi">
            <input className={CONTROL} value={values.note} onChange={set("note")} />
          </Field>
        </div>
        {touched && problems.length ? (
          <ul className="list-disc space-y-0.5 pl-5 text-[12.5px] text-destructive">
            {problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        ) : null}
      </div>
    </AppModal>
  );
}

function CostEntryPicker({
  selected,
  onPick,
  onClear,
}: {
  selected: CostEntryOption | null;
  onPick: (item: CostEntryOption) => void;
  onClear: () => void;
}) {
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const options = useCostEntryOptions(query.trim(), searching);
  if (selected && !searching) {
    return (
      <div className="flex min-w-0 items-end gap-2 text-[13px]">
        <span className="min-w-0 truncate">
          Faktura {selected.invoice_number ?? selected.id} · {selected.seller_name ?? "—"}
          {selected.net_amount != null ? ` · netto ${gr(selected.net_amount)} ${selected.currency ?? ""}` : ""}
        </span>
        <Button size="sm" variant="ghost" onClick={onClear}>
          Odłącz
        </Button>
      </div>
    );
  }
  return (
    <div className="min-w-0">
      <Field label="Z faktury z kolejki kosztów (opcjonalnie)">
        <input
          className={CONTROL}
          value={query}
          onFocus={() => setSearching(true)}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="numer faktury albo sprzedawca"
        />
      </Field>
      {searching ? (
        <div className="mt-1 max-h-48 w-full overflow-y-auto rounded-md border border-border bg-popover">
          {options.isSuccess && options.data.items.length === 0 ? (
            <p className="px-3 py-2 text-[12.5px] text-muted-foreground">Nie ma takiej faktury w kolejce kosztów.</p>
          ) : null}
          {options.isError ? <p className="px-3 py-2 text-[12.5px] text-destructive">Nie udało się wczytać faktur.</p> : null}
          {options.data?.items.map((item) => (
            <button
              key={item.id}
              type="button"
              className="block w-full px-3 py-1.5 text-left text-[12.5px] hover:bg-muted"
              onClick={() => {
                onPick(item);
                setSearching(false);
              }}
            >
              <span className="font-medium">{item.invoice_number ?? `#${item.id}`}</span> · {item.seller_name ?? "—"} ·{" "}
              {datePl(item.issue_date)}
              {item.net_amount != null ? ` · netto ${gr(item.net_amount)} ${item.currency ?? ""}` : ""}
            </button>
          ))}
          <button type="button" className="block w-full px-3 py-1.5 text-left text-[12px] text-muted-foreground hover:bg-muted" onClick={() => setSearching(false)}>
            Zamknij listę
          </button>
        </div>
      ) : null}
    </div>
  );
}

function EquipmentPicker({ selected, onPick }: { selected: EquipmentOption | null; onPick: (item: EquipmentOption | null) => void }) {
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const options = useEquipmentOptions(query.trim(), searching);
  if (selected && !searching) {
    return (
      <div className="flex min-w-0 flex-col gap-1 text-[12px] text-muted-foreground">
        Pozycja „Sprzętu”
        <span className="flex items-center gap-2 text-[13px] text-foreground">
          <span className="min-w-0 truncate">
            {selected.model}
            {selected.inventory_number ? ` · nr ${selected.inventory_number}` : ""}
            {selected.serial_number ? ` · SN ${selected.serial_number}` : ""}
          </span>
          <Button size="sm" variant="ghost" onClick={() => onPick(null)}>
            Odłącz
          </Button>
        </span>
      </div>
    );
  }
  return (
    <div className="min-w-0">
      <Field label="Pozycja „Sprzętu” (gdy dotyczy)">
        <input
          className={CONTROL}
          value={query}
          onFocus={() => setSearching(true)}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="numer inwentarzowy, seryjny albo model"
        />
      </Field>
      {searching ? (
        <div className="mt-1 max-h-48 w-full overflow-y-auto rounded-md border border-border bg-popover">
          {options.isSuccess && options.data.items.length === 0 ? (
            <p className="px-3 py-2 text-[12.5px] text-muted-foreground">Nie ma takiej pozycji bez karty środka.</p>
          ) : null}
          {options.isError ? <p className="px-3 py-2 text-[12.5px] text-destructive">Nie udało się wczytać „Sprzętu”.</p> : null}
          {options.data?.items.map((item) => (
            <button
              key={item.id}
              type="button"
              className="block w-full px-3 py-1.5 text-left text-[12.5px] hover:bg-muted"
              onClick={() => {
                onPick(item);
                setSearching(false);
              }}
            >
              <span className="font-medium">{item.model}</span>
              {item.inventory_number ? ` · nr ${item.inventory_number}` : ""}
              {item.serial_number ? ` · SN ${item.serial_number}` : ""}
            </button>
          ))}
          <button type="button" className="block w-full px-3 py-1.5 text-left text-[12px] text-muted-foreground hover:bg-muted" onClick={() => setSearching(false)}>
            Zamknij listę
          </button>
        </div>
      ) : null}
    </div>
  );
}

/** Ulepszenie, zmiana MPK, likwidacja albo sprzedaż środka. */
export function OperationModal({
  asset,
  type,
  onClose,
}: {
  asset: AssetCard;
  type: Exclude<AssetOperationType, "OT">;
  onClose: () => void;
}) {
  const { config } = useAccounting();
  const { showToast } = useToast();
  const add = useAddAssetOperation();
  const [day, setDay] = useState(config.today);
  const [amount, setAmount] = useState("");
  const [mpk, setMpk] = useState("");
  const [counter, setCounter] = useState("");
  const [note, setNote] = useState("");
  const [touched, setTouched] = useState(false);
  const parsed = amount.trim() ? parseAmount(amount) : null;
  const problems = [
    !/^\d{4}-\d{2}-\d{2}$/.test(day) && "Podaj datę dokumentu.",
    type === "UL" && (parsed == null || parsed.startsWith("-")) && "Podaj wartość ulepszenia większą od zera.",
    type === "SP" && amount.trim() && (parsed == null || parsed.startsWith("-")) && "Cena sprzedaży: kwota większa od zera.",
    type === "MT" && !/^(FO|BO|OG|K\d{1,9})$/.test(mpk.trim().toUpperCase()) && "Nowe MPK: OG, FO, BO albo K<id klienta>.",
  ].filter(Boolean) as string[];

  const submit = () => {
    setTouched(true);
    if (problems.length) return;
    add.mutate(
      {
        id: asset.id,
        body: {
          op_type: type,
          op_date: day,
          amount: type === "UL" || type === "SP" ? parsed : null,
          mpk_to: type === "MT" ? mpk.trim().toUpperCase() : null,
          counter_account: type === "UL" ? counter.trim() || null : null,
          note: note.trim(),
        },
      },
      {
        onSuccess: (result) => {
          showToast(`Zapisano ${result.number}.`);
          onClose();
        },
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać dokumentu."), "error"),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(next) => (next ? null : onClose())}
      size="lg"
      title={`${OPERATION_TITLES[type]} · ${asset.inventory_number}`}
      description={OPERATION_HINTS[type]}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button loading={add.isPending} variant={type === "LT" || type === "SP" ? "destructive" : "primary"} onClick={submit}>
            Zapisz dokument
          </Button>
        </>
      }
    >
      <div className="grid gap-3 text-sm sm:grid-cols-2">
        <Field label="Data dokumentu">
          <input type="date" className={CONTROL} value={day} onChange={(event) => setDay(event.target.value)} />
        </Field>
        {type === "UL" || type === "SP" ? (
          <Field label={type === "UL" ? "Wartość ulepszenia, zł" : "Cena sprzedaży netto, zł (informacyjnie)"}>
            <input
              className={cn(CONTROL, "text-right tabular-nums")}
              value={amount}
              inputMode="decimal"
              onChange={(event) => setAmount(event.target.value)}
            />
          </Field>
        ) : null}
        {type === "MT" ? (
          <Field label={`Nowe MPK (teraz ${asset.mpk_label})`}>
            <input
              className={cn(CONTROL, "uppercase")}
              list="asset-mpk-move"
              value={mpk}
              onChange={(event) => setMpk(event.target.value)}
              placeholder="OG, FO, BO albo K<id klienta>"
            />
            <datalist id="asset-mpk-move">
              {MPK_OPTIONS.filter((option) => option.code !== asset.mpk).map((option) => (
                <option key={option.code} value={option.code}>
                  {option.label}
                </option>
              ))}
            </datalist>
          </Field>
        ) : null}
        {type === "UL" ? (
          <Field label="Konto przeciwstawne (puste = z ustawień, np. 080)">
            <input className={cn(CONTROL, "font-mono")} value={counter} onChange={(event) => setCounter(event.target.value)} />
          </Field>
        ) : null}
        <Field label={type === "LT" ? "Powód likwidacji" : "Uwagi"} className="sm:col-span-2">
          <input className={CONTROL} value={note} onChange={(event) => setNote(event.target.value)} />
        </Field>
        {touched && problems.length ? <p className="text-[12.5px] text-destructive sm:col-span-2">{problems[0]}</p> : null}
      </div>
    </AppModal>
  );
}

/** Ewidencja z Symfonii Środki Trwałe: plik → podgląd → zapis (wszystko albo nic). */
export function ImportModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { period } = useAccounting();
  const { showToast } = useToast();
  const run = useAssetsImport();
  const previous = shiftPeriod(period, -1);
  const [month, setMonth] = useState(`${previous.year}-${String(previous.month).padStart(2, "0")}`);
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<AssetImportResult | null>(null);

  useEffect(() => {
    if (!open) return;
    setResult(null);
    setFile(null);
  }, [open]);

  const send = (save: boolean) => {
    if (!file || !/^\d{4}-\d{2}$/.test(month)) return;
    const [year, monthNo] = month.split("-").map(Number);
    run.mutate(
      { file, year, month: monthNo, save },
      {
        onSuccess: (data) => {
          setResult(data);
          if (data.saved) {
            showToast(`Zapisano ${data.created} środków ze stanem na koniec ${monthText(data.month)}.`);
            onClose();
          }
        },
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się wczytać pliku."), "error"),
      },
    );
  };

  return (
    <AppModal
      open={open}
      onOpenChange={(next) => (next ? null : onClose())}
      size="xl"
      title="Import ewidencji z Symfonii Środki Trwałe"
      description="Plik XLSX albo CSV z ewidencji. Umorzenie z pliku to stan na koniec wybranego miesiąca — NEXUS liczy odpisy od następnego. Środki z importu nie dostają OT w księdze."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Zamknij
          </Button>
          <Button variant="outline" disabled={!file} loading={run.isPending && !result} onClick={() => send(false)}>
            Podgląd
          </Button>
          <Button disabled={!result || result.errors_total > 0 || result.valid === 0} loading={run.isPending && !!result} onClick={() => send(true)}>
            {result ? `Zapisz ${result.valid} środków` : "Zapisz"}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Stan na koniec miesiąca">
            <input type="month" className={CONTROL} value={month} onChange={(event) => setMonth(event.target.value)} />
          </Field>
          <Field label="Plik z Symfonii">
            <input
              type="file"
              accept=".xlsx,.csv,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              className="text-[13px]"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setResult(null);
              }}
            />
          </Field>
        </div>
        <p className="text-[12px] text-muted-foreground">
          Kolumny po nazwach: „Nazwa”, „Data przyjęcia”, „Wartość początkowa” (wymagane) oraz numer inwentarzowy, KŚT, rodzaj,
          umorzenie bilansowe i podatkowe, metoda, stawki, konta, MPK. Środki zlikwidowane i sprzedane są pomijane.
        </p>
        {result ? <ImportSummary result={result} /> : null}
      </div>
    </AppModal>
  );
}

function ImportSummary({ result }: { result: AssetImportResult }) {
  return (
    <div className="space-y-2">
      <p className="text-[13px]">
        Środków w pliku: {result.rows} · poprawnych: {result.valid} · z błędami: {result.errors_total}
        {result.skipped_disposed ? ` · pominięte zbyte: ${result.skipped_disposed}` : ""} · wartość {gr(result.totals.initial)} zł ·
        umorzenie {gr(result.totals.balance)} zł
      </p>
      {result.missing_accounts.length ? (
        <p className="text-[12.5px] text-destructive">Kont nie ma w planie kont: {result.missing_accounts.join(", ")}.</p>
      ) : null}
      {result.errors.length ? (
        <ul className="max-h-32 list-disc space-y-0.5 overflow-y-auto pl-5 text-[12.5px] text-destructive">
          {result.errors.map((error) => (
            <li key={error.line}>
              Wiersz {error.line}: {error.problems.join(" ")}
            </li>
          ))}
        </ul>
      ) : null}
      {result.preview.length ? (
        <div className="max-h-[40dvh] overflow-y-auto rounded-md border border-border">
          <table className="w-full table-fixed text-[12.5px]">
            <thead>
              <tr className="border-b border-border/70">
                <th className={cn(CALM_HEAD, "w-[7%] px-2 py-1.5 text-left")}>Wiersz</th>
                <th className={cn(CALM_HEAD, "px-2 py-1.5 text-left")}>Środek</th>
                <th className={cn(CALM_HEAD, "w-[12%] px-2 py-1.5 text-left")}>Przyjęto</th>
                <th className={cn(CALM_HEAD, "w-[16%] px-2 py-1.5 text-right")}>Wartość</th>
                <th className={cn(CALM_HEAD, "w-[16%] px-2 py-1.5 text-right")}>Umorzenie</th>
                <th className={cn(CALM_HEAD, "w-[14%] px-2 py-1.5 text-left")}>Plan</th>
              </tr>
            </thead>
            <tbody>
              {result.preview.map((row) => (
                <tr key={row.line} className={CALM_ROW}>
                  <td className="px-2 py-1.5 tabular-nums">{row.line}</td>
                  <td className="truncate px-2 py-1.5">
                    {row.inventory_number ?? "nowy numer"} · {row.name}
                  </td>
                  <td className="px-2 py-1.5 tabular-nums">{datePl(row.accepted_on)}</td>
                  <td className={cn(CALM_AMOUNT, "px-2 py-1.5")}>{gr(row.initial_value)}</td>
                  <td className={cn(CALM_AMOUNT, "px-2 py-1.5")}>{gr(row.balance)}</td>
                  <td className="px-2 py-1.5">
                    {METHOD_LABELS[row.balance_method]} {row.balance_rate ? `${row.balance_rate.replace(".00", "")}%` : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

/** Konta modułu (administrator): amortyzacja, przyjęcie i ulepszenie, zbycie. */
export function AccountsModal({ open, accounts, onClose }: { open: boolean; accounts: AssetsAccounts; onClose: () => void }) {
  const { showToast } = useToast();
  const save = useSetAssetsAccounts();
  const [values, setValues] = useState(accounts);
  useEffect(() => {
    if (open) setValues(accounts);
  }, [open, accounts]);
  const set = (key: keyof AssetsAccounts) => (event: ChangeEvent<HTMLInputElement>) =>
    setValues((current) => ({ ...current, [key]: event.target.value }));
  return (
    <AppModal
      open={open}
      onOpenChange={(next) => (next ? null : onClose())}
      size="md"
      title="Konta środków trwałych"
      description="Każde konto musi być w planie kont. Podział AM na „5” bierze konta z rozliczenia kosztów (Ustawienia)."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button
            loading={save.isPending}
            onClick={() =>
              save.mutate(values, {
                onSuccess: () => {
                  showToast("Zapisano konta środków trwałych.");
                  onClose();
                },
                onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać kont."), "error"),
              })
            }
          >
            Zapisz konta
          </Button>
        </>
      }
    >
      <div className="grid gap-3 text-sm">
        <Field label="Amortyzacja (Wn w AM), np. 401">
          <input className={cn(CONTROL, "font-mono")} value={values.cost_account} onChange={set("cost_account")} />
        </Field>
        <Field label="Przyjęcie i ulepszenie — konto przeciwstawne, np. 080">
          <input className={cn(CONTROL, "font-mono")} value={values.intake_account} onChange={set("intake_account")} />
        </Field>
        <Field label="Likwidacja i sprzedaż — wartość netto, np. 761">
          <input className={cn(CONTROL, "font-mono")} value={values.disposal_account} onChange={set("disposal_account")} />
        </Field>
      </div>
    </AppModal>
  );
}
