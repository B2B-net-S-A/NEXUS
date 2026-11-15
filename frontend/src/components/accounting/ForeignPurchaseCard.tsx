"use client";

import Link from "next/link";
import { useState } from "react";

import { QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useCreateForeignPurchase,
  useForeignPurchases,
  type ForeignOverview,
  type ForeignPurchase,
  type ForeignPurchaseInput,
} from "@/lib/api/accounting-vat";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { SectionCard } from "./AccountingShell";
import { datePl, gr } from "./ledger-model";
import { GROUP_SHORT, IMPORT_GROUP_LABEL, netValid, supplierGroup } from "./vat-model";

const CONTROL = "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";
const NOTE = "px-3.5 py-2.5 text-[13px] text-muted-foreground";
const NEW = "new";

/** Kurs NBP jak w wyciągu: „4,3000 z 19.03.2026”. */
function rateLabel(item: Pick<ForeignPurchase, "currency" | "rate" | "rate_day">): string | null {
  if (item.currency === "PLN" || !item.rate) return null;
  const rate = Number(item.rate).toLocaleString("pl-PL", { minimumFractionDigits: 4, maximumFractionDigits: 6 });
  return `kurs ${rate}${item.rate_day ? ` z ${datePl(item.rate_day)}` : ""}`;
}

/**
 * Zakupy zagraniczne miesiąca (K5b-2): faktury dostawców spoza KSeF (import
 * usług — LinkedIn, Google, Microsoft…) wpisane formularzem. Każda to FVZ
 * w buforze: VAT należny w rejestrze sprzedaży (K_27/K_28 albo K_29/K_30)
 * i — przy odliczeniu — naliczony w rejestrze zakupu. Zatwierdza lista
 * „Księgowi” w Dokumentach.
 */
export function ForeignPurchaseCard({ year, month }: { year: number; month: number }) {
  const overview = useForeignPurchases(year, month);
  const [adding, setAdding] = useState(false);
  if (overview.isError) {
    return (
      <SectionCard title="Zakupy zagraniczne">
        <div className="p-3.5">
          <QueryStateNotice state="error" onRetry={() => overview.refetch()} />
        </div>
      </SectionCard>
    );
  }
  if (!overview.isSuccess) return null;
  const data = overview.data;
  return (
    <SectionCard title={`Zakupy zagraniczne · ${data.items.length}`} aside="import usług bez KSeF · FVZ do bufora">
      {data.items.length ? (
        <PurchasesTable data={data} />
      ) : (
        <p className={NOTE}>W tym miesiącu nie ma faktur od dostawców zagranicznych.</p>
      )}
      {adding ? (
        <ForeignForm data={data} onClose={() => setAdding(false)} />
      ) : (
        <div className="border-t border-border/70 px-3.5 py-2">
          <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
            Dodaj fakturę zagraniczną
          </Button>
        </div>
      )}
    </SectionCard>
  );
}

function PurchasesTable({ data }: { data: ForeignOverview }) {
  const query = `year=${data.year}&month=${data.month}&type=FVZ`;
  return (
    <table className="w-full table-fixed text-sm">
      <thead>
        <tr className="border-b border-border/70">
          <th className={cn(CALM_HEAD, "w-[20%] px-3.5 py-2 text-left")}>Faktura</th>
          <th className={cn(CALM_HEAD, "px-2 py-2 text-left")}>Dostawca</th>
          <th className={cn(CALM_HEAD, "w-[11%] px-2 py-2 text-left")}>Usługa</th>
          <th className={cn(CALM_HEAD, "w-[17%] px-2 py-2 text-right")}>W walucie</th>
          <th className={cn(CALM_HEAD, "w-[12%] px-2 py-2 text-right")}>Netto zł</th>
          <th className={cn(CALM_HEAD, "w-[11%] py-2 pl-2 pr-3.5 text-right")}>VAT zł</th>
        </tr>
      </thead>
      <tbody>
        {data.items.map((item) => (
          <tr key={item.id} className={cn(CALM_ROW, "last:border-0")}>
            <td className="min-w-0 px-3.5 py-1.5">
              <Link
                className="block truncate font-medium text-primary hover:underline"
                href={`/accounting/documents?${query}&status=${item.status}`}
              >
                {item.number}
              </Link>
              <span className={cn(CALM_SUBLINE, item.status === "draft" ? "text-warning-muted-foreground" : "")}>
                {item.status_label}
                {item.deduction === "none" ? " · bez odliczenia" : ""}
              </span>
            </td>
            <td className="min-w-0 px-2 py-1.5">
              <span className="block truncate">{item.supplier ?? "—"}</span>
              <span className={CALM_SUBLINE}>{item.group ? GROUP_SHORT[item.group] : "—"}</span>
            </td>
            <td className="px-2 py-1.5 text-[13px] tabular-nums">{datePl(item.service_date)}</td>
            <td className="px-2 py-1.5 text-right">
              <span className={cn(CALM_AMOUNT, "block")}>
                {item.net_cur != null ? `${gr(item.net_cur)} ${item.currency}` : "—"}
              </span>
              {rateLabel(item) ? <span className={CALM_SUBLINE}>{rateLabel(item)}</span> : null}
            </td>
            <td className={cn(CALM_AMOUNT, "px-2 py-1.5 text-right")}>{item.net != null ? gr(item.net) : "—"}</td>
            <td className={cn(CALM_AMOUNT, "py-1.5 pl-2 pr-3.5 text-right")}>
              {item.vat != null ? gr(item.vat) : "—"}
              {item.vat_rate ? <span className={CALM_SUBLINE}>{item.vat_rate}%</span> : null}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

interface FormState {
  supplier: string;
  name: string;
  country: string;
  taxId: string;
  symfonia: string;
  account: string;
  number: string;
  issueDate: string;
  serviceDate: string;
  currency: string;
  net: string;
  vatRate: "23" | "8" | "5";
  deduction: "full" | "none";
  costAccount: string;
  description: string;
}

function emptyForm(data: ForeignOverview, keep?: Pick<FormState, "supplier" | "currency" | "costAccount">): FormState {
  return {
    supplier: keep?.supplier ?? "",
    name: "",
    country: "",
    taxId: "",
    symfonia: "",
    account: "",
    number: "",
    issueDate: "",
    serviceDate: "",
    currency: keep?.currency ?? (data.currencies.includes("EUR") ? "EUR" : "PLN"),
    net: "",
    vatRate: "23",
    deduction: "full",
    costAccount: keep?.costAccount ?? "",
    description: "",
  };
}

/** Treść żądania z formularza (bez pustych pól opcjonalnych). */
function foreignBody(form: FormState): ForeignPurchaseInput {
  const optional = (value: string) => value.trim() || undefined;
  return {
    ...(form.supplier === NEW
      ? {
          new_supplier: {
            name: form.name.trim(),
            country: form.country.trim().toUpperCase(),
            tax_id: optional(form.taxId),
            symfonia_partner_id: optional(form.symfonia),
            account: optional(form.account),
          },
        }
      : { supplier_id: Number(form.supplier) }),
    number: form.number.trim(),
    issue_date: form.issueDate,
    service_date: form.serviceDate,
    currency: form.currency,
    net: form.net.replace(/\s/g, "").replace(",", "."),
    vat_rate: form.vatRate,
    deduction: form.deduction,
    cost_account: form.costAccount.trim(),
    description: optional(form.description),
  };
}

function ForeignForm({ data, onClose }: { data: ForeignOverview; onClose: () => void }) {
  const { showToast } = useToast();
  const create = useCreateForeignPurchase();
  const [form, setForm] = useState<FormState>(() => emptyForm(data));
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((prev) => ({ ...prev, [key]: value }));
  const creating = form.supplier === NEW;
  const chosen = data.suppliers.find((item) => String(item.id) === form.supplier);
  const group = creating ? supplierGroup(form.country, form.taxId) : chosen?.group;
  const supplierReady = creating
    ? form.name.trim().length >= 2 &&
      /^[A-Za-z]{2}$/.test(form.country.trim()) &&
      form.country.trim().toUpperCase() !== "PL" &&
      Boolean(form.taxId.trim() || form.symfonia.trim())
    : Boolean(chosen);
  const ready =
    supplierReady &&
    Boolean(form.number.trim() && form.issueDate && form.serviceDate && form.costAccount.trim()) &&
    netValid(form.net);
  const submit = () =>
    create.mutate(foreignBody(form), {
      onSuccess: (result) => {
        const doc = result.document;
        showToast(
          `FVZ ${doc.number} w buforze: ${gr(doc.net ?? 0)} zł netto, VAT ${gr(doc.vat ?? 0)} zł. Zatwierdza lista „Księgowi” w Dokumentach.`,
        );
        setForm(emptyForm(data, { supplier: String(result.supplier.id), currency: form.currency, costAccount: form.costAccount }));
      },
      onError: (error) => showToast(apiErrorMessage(error, "Nie udało się dodać faktury."), "error"),
    });
  return (
    <form
      className="space-y-2.5 border-t border-border/70 px-3.5 py-3 text-[13px]"
      onSubmit={(event) => {
        event.preventDefault();
        if (ready) submit();
      }}
    >
      <div className="flex flex-wrap items-end gap-2.5">
        <label className="flex min-w-[16rem] flex-1 flex-col gap-1">
          <span className="text-muted-foreground">Dostawca</span>
          <select
            className={cn(CONTROL, "w-full")}
            aria-label="Dostawca"
            value={form.supplier}
            onChange={(event) => set("supplier", event.target.value)}
          >
            <option value="">Wybierz z kartoteki…</option>
            {data.suppliers.map((item) => (
              <option key={item.id} value={String(item.id)}>
                {[item.name, item.country, item.tax_id].filter(Boolean).join(" · ")}
              </option>
            ))}
            <option value={NEW} disabled={!data.foreign_account}>
              + Nowy dostawca{data.foreign_account ? "" : " (najpierw konto dostawców w Kontach VAT)"}
            </option>
          </select>
        </label>
        {group ? <p className="pb-1.5 text-[12px] text-muted-foreground">JPK: {IMPORT_GROUP_LABEL[group]}</p> : null}
      </div>
      {data.missing.length ? (
        <p className="text-[12px] text-warning-muted-foreground">Brakuje: {data.missing.join("; ")}.</p>
      ) : null}
      {creating ? (
        <fieldset className="flex flex-wrap items-end gap-2.5 rounded-md border border-border/70 px-2.5 py-2">
          <legend className="px-1 text-[12px] text-muted-foreground">Nowy dostawca do kartoteki</legend>
          <label className="flex min-w-[14rem] flex-1 flex-col gap-1">
            <span className="text-muted-foreground">Nazwa</span>
            <input className={cn(CONTROL, "w-full")} aria-label="Nazwa dostawcy" value={form.name} onChange={(event) => set("name", event.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Kraj</span>
            <input
              className={cn(CONTROL, "w-16 uppercase")}
              aria-label="Kraj dostawcy"
              maxLength={2}
              placeholder="IE"
              value={form.country}
              onChange={(event) => set("country", event.target.value.replace(/[^A-Za-z]/g, ""))}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Numer VAT UE / podatkowy</span>
            <input className={cn(CONTROL, "w-44")} aria-label="Numer VAT dostawcy" value={form.taxId} onChange={(event) => set("taxId", event.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">ID Symfonii (opcjonalnie)</span>
            <input className={cn(CONTROL, "w-32")} aria-label="ID Symfonii" value={form.symfonia} onChange={(event) => set("symfonia", event.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Konto rozrachunkowe</span>
            <input
              className={cn(CONTROL, "w-32 tabular-nums")}
              aria-label="Konto rozrachunkowe dostawcy"
              placeholder={data.next_account ?? ""}
              value={form.account}
              onChange={(event) => set("account", event.target.value)}
            />
          </label>
        </fieldset>
      ) : null}
      <div className="flex flex-wrap items-end gap-2.5">
        <label className="flex min-w-[10rem] flex-1 flex-col gap-1">
          <span className="text-muted-foreground">Numer faktury</span>
          <input className={cn(CONTROL, "w-full")} aria-label="Numer faktury" value={form.number} onChange={(event) => set("number", event.target.value)} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-muted-foreground">Data wystawienia</span>
          <input
            type="date"
            className={cn(CONTROL, "w-36")}
            aria-label="Data wystawienia"
            value={form.issueDate}
            onChange={(event) => {
              const value = event.target.value;
              // Usługa zwykle z dnia faktury — data wykonania idzie za wystawieniem, dopóki ktoś jej nie zmieni.
              setForm((prev) => ({ ...prev, issueDate: value, serviceDate: !prev.serviceDate || prev.serviceDate === prev.issueDate ? value : prev.serviceDate }));
            }}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-muted-foreground">Wykonanie usługi</span>
          <input
            type="date"
            className={cn(CONTROL, "w-36")}
            aria-label="Data wykonania usługi"
            value={form.serviceDate}
            onChange={(event) => set("serviceDate", event.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-muted-foreground">Waluta</span>
          <select className={cn(CONTROL, "w-24")} aria-label="Waluta" value={form.currency} onChange={(event) => set("currency", event.target.value)}>
            {data.currencies.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-muted-foreground">Netto w walucie</span>
          <input
            className={cn(CONTROL, "w-32 tabular-nums", form.net && !netValid(form.net) ? "border-destructive" : "")}
            aria-label="Netto w walucie"
            inputMode="decimal"
            placeholder="1234,56"
            value={form.net}
            onChange={(event) => set("net", event.target.value)}
          />
        </label>
      </div>
      <div className="flex flex-wrap items-end gap-2.5">
        <label className="flex flex-col gap-1">
          <span className="text-muted-foreground">Stawka VAT</span>
          <select className={cn(CONTROL, "w-20")} aria-label="Stawka VAT" value={form.vatRate} onChange={(event) => set("vatRate", event.target.value as FormState["vatRate"])}>
            {(["23", "8", "5"] as const).map((rate) => (
              <option key={rate} value={rate}>
                {rate}%
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-muted-foreground">VAT naliczony</span>
          <select
            className={cn(CONTROL, "w-40")}
            aria-label="Odliczenie VAT"
            value={form.deduction}
            onChange={(event) => set("deduction", event.target.value as FormState["deduction"])}
          >
            <option value="full">odliczenie 100%</option>
            <option value="none">bez odliczenia</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-muted-foreground">Konto kosztu</span>
          <input
            className={cn(CONTROL, "w-28 tabular-nums")}
            aria-label="Konto kosztu"
            placeholder="np. 402-1"
            value={form.costAccount}
            onChange={(event) => set("costAccount", event.target.value)}
          />
        </label>
        <label className="flex min-w-[12rem] flex-1 flex-col gap-1">
          <span className="text-muted-foreground">Opis (opcjonalnie)</span>
          <input className={cn(CONTROL, "w-full")} aria-label="Opis dokumentu" value={form.description} onChange={(event) => set("description", event.target.value)} />
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-2.5">
        <Button size="sm" type="submit" disabled={!ready} loading={create.isPending}>
          Dodaj do bufora
        </Button>
        <Button size="sm" type="button" variant="outline" onClick={onClose}>
          Zamknij
        </Button>
        <p className="text-[12px] text-muted-foreground">
          Kurs: średni NBP z ostatniego dnia roboczego przed wykonaniem usługi (art. 31a) — przeliczy NEXUS. Kwota ujemna = korekta.
        </p>
      </div>
    </form>
  );
}
