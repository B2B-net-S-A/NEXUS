"use client";

import { useEffect, useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { apiErrorMessage } from "@/lib/api-error";
import type { CostCategory } from "@/lib/api/finance-ledger";
import {
  useAccountSave,
  useAccounts,
  useCounterpartyOptions,
  useRuleSave,
  useRules,
  type Account,
  type AccountKind,
  type Deduction,
  type PostingRule,
  type Register,
  type RuleInput,
} from "@/lib/api/finance-posting";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { CATEGORY_LABELS, CATEGORY_ORDER } from "./ledger-model";
import {
  DEDUCTION_LABELS,
  REGISTER_LABELS,
  TEMPLATE_FIELDS,
  previewDescription,
  unknownTemplateFields,
} from "./posting-model";

const CONTROL =
  "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";
const LABEL = "text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground";
const KIND_LABELS: Record<AccountKind, string> = {
  cost: "koszt",
  vat: "VAT",
  settlement: "rozrachunek",
  revenue: "przychód",
  // 0699 (K1): konta księgi spoza dekretu faktur — zakłada je plan kont w Księgowości.
  other: "inne",
};
const KIND_ORDER: readonly AccountKind[] = ["cost", "vat", "settlement", "revenue"];

function Mono({ value }: { value: string | null }) {
  return value ? <span className="font-mono text-[12.5px]">{value}</span> : <span className={CALM_EMPTY}>—</span>;
}

// ── Plan kont ────────────────────────────────────────────────────────────────

function AccountForm({ row, onDone }: { row?: Account; onDone: () => void }) {
  const save = useAccountSave();
  const { showToast } = useToast();
  const [number, setNumber] = useState(row?.number ?? "");
  const [name, setName] = useState(row?.name ?? "");
  const [kind, setKind] = useState<AccountKind>(row?.kind ?? "cost");
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {row ? null : (
        <Input
          aria-label="Numer konta"
          placeholder="np. 402-210"
          value={number}
          onChange={(event) => setNumber(event.target.value)}
          className="h-8 w-28 font-mono text-[12.5px]"
        />
      )}
      <Input
        aria-label="Nazwa konta"
        placeholder="Nazwa"
        value={name}
        onChange={(event) => setName(event.target.value)}
        className="h-8 min-w-0 flex-1"
      />
      <select aria-label="Rodzaj konta" value={kind} onChange={(e) => setKind(e.target.value as AccountKind)} className={CONTROL}>
        {KIND_ORDER.map((item) => (
          <option key={item} value={item}>
            {KIND_LABELS[item]}
          </option>
        ))}
      </select>
      <Button
        size="sm"
        loading={save.isPending}
        disabled={!name.trim() || (!row && !number.trim())}
        onClick={() =>
          save.mutate(row ? { id: row.id, name, kind } : { number, name, kind }, {
            onSuccess: () => {
              showToast(row ? "Konto zapisane." : "Konto dodane.", "success");
              onDone();
            },
            onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać konta."), "error"),
          })
        }
      >
        Zapisz
      </Button>
      <Button size="sm" variant="ghost" onClick={onDone}>
        Anuluj
      </Button>
    </div>
  );
}

function AccountsSection({ canWrite }: { canWrite: boolean }) {
  const accounts = useAccounts();
  const save = useAccountSave();
  const { showToast } = useToast();
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const items = accounts.data ?? [];
  return (
    <section aria-label="Plan kont" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className={LABEL}>Plan kont Symfonii FK</h2>
        <span className="text-xs text-muted-foreground">
          Konta analityczne kontrahentów (201-2-…, 200-2-…) są w „Kontrahenci”.
        </span>
        {canWrite && editing !== "new" ? (
          <Button size="sm" variant="outline" className="ml-auto" onClick={() => setEditing("new")}>
            Dodaj konto
          </Button>
        ) : null}
      </div>
      {editing === "new" ? <AccountForm onDone={() => setEditing(null)} /> : null}
      {accounts.isLoading ? (
        <p className="py-4 text-sm text-muted-foreground">Wczytywanie planu kont…</p>
      ) : accounts.isError ? (
        <QueryStateNotice state="error" onRetry={() => accounts.refetch()} />
      ) : accounts.isSuccess && items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          Plan kont jest pusty.
        </p>
      ) : (
        <div className="rounded-lg border border-border bg-card">
          <Table density="compact" className="table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead className={`${CALM_HEAD} w-[16%]`}>Konto</TableHead>
                <TableHead className={`${CALM_HEAD} w-[44%]`}>Nazwa</TableHead>
                <TableHead className={`${CALM_HEAD} w-[14%]`}>Rodzaj</TableHead>
                <TableHead className={`${CALM_HEAD} w-[26%]`} />
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((row) => (
                <TableRow key={row.id} className={cn(CALM_ROW, !row.active && "opacity-60")}>
                  <TableCell>
                    <Mono value={row.number} />
                  </TableCell>
                  <TableCell className="min-w-0">
                    {editing === row.id ? (
                      <AccountForm row={row} onDone={() => setEditing(null)} />
                    ) : (
                      <>
                        <span className="block truncate">{row.name}</span>
                        {row.rules > 0 ? (
                          <span className={CALM_SUBLINE}>w regułach: {row.rules}</span>
                        ) : null}
                      </>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge size="sm" variant={row.active ? "neutral" : "outline"}>
                      {row.active ? row.kind_label : "wyłączone"}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    {canWrite && editing !== row.id ? (
                      <span className="flex justify-end gap-1">
                        <Button size="sm" variant="ghost" onClick={() => setEditing(row.id)}>
                          Edytuj
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={save.isPending}
                          onClick={() =>
                            save.mutate(
                              { id: row.id, active: !row.active },
                              {
                                onError: (err) =>
                                  showToast(apiErrorMessage(err, "Nie udało się zmienić konta."), "error"),
                              },
                            )
                          }
                        >
                          {row.active ? "Wyłącz" : "Włącz"}
                        </Button>
                      </span>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </section>
  );
}

// ── Reguły dekretu ───────────────────────────────────────────────────────────

function CounterpartyPicker({
  value,
  onChange,
}: {
  value: { id: number; name: string } | null;
  onChange: (value: { id: number; name: string } | null) => void;
}) {
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setQ(search), 300);
    return () => window.clearTimeout(timer);
  }, [search]);
  const options = useCounterpartyOptions(q);
  if (value) {
    return (
      <span className="flex items-center gap-1.5 text-sm">
        {value.name}
        <Button size="sm" variant="ghost" onClick={() => onChange(null)}>
          Każdy kontrahent
        </Button>
      </span>
    );
  }
  return (
    <span className="relative">
      <Input
        aria-label="Kontrahent reguły"
        placeholder="Każdy kontrahent — albo szukaj nazwy, NIP-u"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        className="h-8 w-72"
      />
      {(options.data ?? []).length > 0 ? (
        <ul className="absolute z-10 mt-1 max-h-56 w-72 overflow-y-auto rounded-md border border-border bg-popover py-1 text-sm shadow-md">
          {(options.data ?? []).map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className="w-full px-2.5 py-1 text-left hover:bg-accent"
                onClick={() => {
                  onChange({ id: item.id, name: item.name });
                  setSearch("");
                }}
              >
                {item.name}
                <span className="ml-1.5 text-xs text-muted-foreground">
                  {item.id_value ?? ""} {item.cost_account ? `· ${item.cost_account}` : "· bez konta"}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </span>
  );
}

function RuleForm({ row, onDone }: { row?: PostingRule; onDone: () => void }) {
  const save = useRuleSave();
  const { showToast } = useToast();
  const [category, setCategory] = useState<CostCategory>(row?.category ?? "office");
  const [party, setParty] = useState<{ id: number; name: string } | null>(
    row?.counterparty_id ? { id: row.counterparty_id, name: row.counterparty_name ?? "" } : null,
  );
  const [form, setForm] = useState({
    cost_account: row?.cost_account ?? "",
    vat_account: row?.vat_account ?? "221",
    deduction: (row?.deduction ?? "full") as Deduction,
    register: (row?.register ?? "purchase") as Register,
    doc_type: row?.doc_type ?? "FVZ",
    service_label: row?.service_label ?? "",
    description_template: row?.description_template ?? "{usługa} {MM}/{RRRR}",
  });
  const unknown = unknownTemplateFields(form.description_template);
  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((current) => ({ ...current, [key]: value }));
  const submit = () => {
    const body: RuleInput & { id?: number } = {
      ...form,
      vat_account: form.deduction === "full" ? form.vat_account : form.vat_account || null,
    };
    if (row) body.id = row.id;
    else {
      body.category = category;
      body.counterparty_id = party?.id ?? null;
    }
    save.mutate(body, {
      onSuccess: () => {
        showToast(row ? "Reguła zapisana." : "Reguła dodana.", "success");
        onDone();
      },
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać reguły."), "error"),
    });
  };
  return (
    <div className="space-y-2 rounded-lg border border-border bg-card p-3.5 text-sm" aria-label="Reguła dekretu">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted-foreground">Gdy</span>
        {row ? (
          <b>{row.label}</b>
        ) : (
          <>
            <select
              aria-label="Kategoria"
              value={category}
              onChange={(e) => setCategory(e.target.value as CostCategory)}
              className={CONTROL}
            >
              {CATEGORY_ORDER.map((item) => (
                <option key={item} value={item}>
                  {CATEGORY_LABELS[item]}
                </option>
              ))}
            </select>
            <CounterpartyPicker value={party} onChange={setParty} />
          </>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted-foreground">Wn koszt</span>
        <Input
          aria-label="Konto kosztu"
          value={form.cost_account}
          onChange={(e) => set("cost_account", e.target.value)}
          className="h-8 w-24 font-mono text-[12.5px]"
        />
        <span className="text-muted-foreground">odliczenie</span>
        <select
          aria-label="Odliczenie VAT"
          value={form.deduction}
          onChange={(e) => set("deduction", e.target.value as Deduction)}
          className={CONTROL}
        >
          {(Object.keys(DEDUCTION_LABELS) as Deduction[]).map((item) => (
            <option key={item} value={item}>
              {DEDUCTION_LABELS[item]}
            </option>
          ))}
        </select>
        {form.deduction === "full" ? (
          <>
            <span className="text-muted-foreground">Wn VAT</span>
            <Input
              aria-label="Konto VAT"
              value={form.vat_account}
              onChange={(e) => set("vat_account", e.target.value)}
              className="h-8 w-20 font-mono text-[12.5px]"
            />
          </>
        ) : null}
        <span className="text-muted-foreground">Ma: konto kontrahenta z kartoteki</span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="Rejestr"
          value={form.register}
          onChange={(e) => set("register", e.target.value as Register)}
          className={CONTROL}
        >
          {(Object.keys(REGISTER_LABELS) as Register[]).map((item) => (
            <option key={item} value={item}>
              {REGISTER_LABELS[item]}
            </option>
          ))}
        </select>
        <Input
          aria-label="Typ dokumentu"
          value={form.doc_type}
          maxLength={8}
          onChange={(e) => set("doc_type", e.target.value)}
          className="h-8 w-20 font-mono uppercase"
        />
        <Input
          aria-label="Usługa"
          placeholder="Usługa (np. Usługi IT)"
          value={form.service_label}
          onChange={(e) => set("service_label", e.target.value)}
          className="h-8 w-44"
        />
        <Input
          aria-label="Wzór opisu"
          value={form.description_template}
          onChange={(e) => set("description_template", e.target.value)}
          className="h-8 min-w-0 flex-1 font-mono text-[12.5px]"
        />
      </div>
      <p className={cn("text-xs", unknown.length ? "text-destructive" : "text-muted-foreground")}>
        {unknown.length
          ? `Nieznane pole: {${unknown[0]}}. Dozwolone: ${TEMPLATE_FIELDS.join(", ")}.`
          : `Przykład: „${previewDescription(form.description_template, form.service_label || "Usługi IT", {
              year: 2026,
              month: 10,
            })}”`}
      </p>
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={onDone}>
          Anuluj
        </Button>
        <Button size="sm" loading={save.isPending} disabled={unknown.length > 0} onClick={submit}>
          Zapisz regułę
        </Button>
      </div>
    </div>
  );
}

function RulesSection({ canWrite }: { canWrite: boolean }) {
  const rules = useRules();
  const save = useRuleSave();
  const { showToast } = useToast();
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const items = rules.data ?? [];
  return (
    <section aria-label="Reguły dekretu" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className={LABEL}>Reguły dekretu</h2>
        <span className="text-xs text-muted-foreground">
          Reguła kontrahenta wygrywa z ogólną reguły kategorii.
        </span>
        {canWrite && editing !== "new" ? (
          <Button size="sm" variant="outline" className="ml-auto" onClick={() => setEditing("new")}>
            Dodaj regułę
          </Button>
        ) : null}
      </div>
      {editing === "new" ? <RuleForm onDone={() => setEditing(null)} /> : null}
      {rules.isLoading ? (
        <p className="py-4 text-sm text-muted-foreground">Wczytywanie reguł…</p>
      ) : rules.isError ? (
        <QueryStateNotice state="error" onRetry={() => rules.refetch()} />
      ) : rules.isSuccess && items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          Nie ma reguł — bez reguły dekret faktury nie powstanie.
        </p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((rule) =>
            editing === rule.id ? (
              <li key={rule.id}>
                <RuleForm row={rule} onDone={() => setEditing(null)} />
              </li>
            ) : (
              <li
                key={rule.id}
                className={cn(
                  "flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-border bg-card px-3.5 py-2 text-sm",
                  !rule.active && "opacity-60",
                )}
              >
                <b>{rule.label}</b>
                <span>
                  Wn <Mono value={rule.cost_account} />
                  {rule.deduction === "full" ? (
                    <>
                      {" "}+ VAT <Mono value={rule.vat_account} />
                    </>
                  ) : (
                    " (VAT bez odliczenia)"
                  )}{" "}
                  · Ma konto kontrahenta
                </span>
                <span className="text-muted-foreground">
                  {rule.register_label} · {rule.doc_type} · {rule.service_label} ·{" "}
                  <span className="font-mono text-[12px]">{rule.description_template}</span>
                </span>
                {!rule.active ? <Badge size="sm" variant="outline">wyłączona</Badge> : null}
                {canWrite ? (
                  <span className="ml-auto flex gap-1">
                    <Button size="sm" variant="ghost" onClick={() => setEditing(rule.id)}>
                      Edytuj
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={save.isPending}
                      onClick={() =>
                        save.mutate(
                          { id: rule.id, active: !rule.active },
                          {
                            onError: (err) =>
                              showToast(apiErrorMessage(err, "Nie udało się zmienić reguły."), "error"),
                          },
                        )
                      }
                    >
                      {rule.active ? "Wyłącz" : "Włącz"}
                    </Button>
                  </span>
                ) : null}
              </li>
            ),
          )}
        </ul>
      )}
    </section>
  );
}

/** Finanse → „Plan kont”: konta Symfonii FK i reguły dekretu (E2). */
export function ChartTab({ canWrite = true }: { canWrite?: boolean }) {
  return (
    <div className="space-y-5">
      <RulesSection canWrite={canWrite} />
      <AccountsSection canWrite={canWrite} />
    </div>
  );
}
