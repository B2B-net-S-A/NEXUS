"use client";

import { useEffect, useRef, useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiErrorMessage } from "@/lib/api-error";
import {
  QUEUE_PAGE,
  useCounterparties,
  useCounterpartyImport,
  useCounterpartyPatch,
  type Counterparty,
  type CounterpartyRole,
  type ImportSummary,
} from "@/lib/api/finance-ledger";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";

import { ROLE_LABELS } from "./ledger-model";

const CONTROL =
  "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";
const ROLE_ORDER: readonly CounterpartyRole[] = ["client", "team", "contractor", "supplier"];
const ROLE_VARIANT: Record<CounterpartyRole, "soft" | "success" | "info" | "neutral"> = {
  client: "soft",
  team: "info",
  contractor: "success",
  supplier: "neutral",
};

function Mono({ value }: { value: string | null }) {
  return value ? (
    <span className="font-mono text-[12.5px]">{value}</span>
  ) : (
    <span className={CALM_EMPTY}>—</span>
  );
}

function ImportPreview({
  summary,
  saving,
  onSave,
  onCancel,
}: {
  summary: ImportSummary;
  saving: boolean;
  onSave: () => void;
  onCancel: () => void;
}) {
  const nothing = summary.created + summary.changed === 0;
  return (
    <section
      aria-label="Podgląd importu"
      className="space-y-2.5 rounded-lg border border-border bg-card p-3.5 text-sm"
    >
      <p>
        {summary.saved ? "Zapisano: " : "Plik: "}
        <b>{countPl(summary.created, "nowy", "nowe", "nowych")}</b>,{" "}
        <b>{countPl(summary.changed, "zmieniony", "zmienione", "zmienionych")}</b>,{" "}
        {summary.unchanged} bez zmian
        {summary.error_count > 0 ? (
          <>
            , <b className="text-destructive">{countPl(summary.error_count, "błąd", "błędy", "błędów")}</b>
          </>
        ) : null}
        .{summary.saved && summary.linked_entries > 0
          ? ` Powiązano z kolejką kosztów: ${countPl(summary.linked_entries, "faktura", "faktury", "faktur")}.`
          : ""}
      </p>
      <p className="text-xs text-muted-foreground">
        Rozpoznane kolumny: {summary.columns.join(", ")}. Pusta komórka niczego nie kasuje.
      </p>
      {summary.errors.length > 0 ? (
        <ul className="max-h-40 space-y-0.5 overflow-y-auto text-xs">
          {summary.errors.map((error) => (
            <li key={`${error.line}-${error.message}`}>
              wiersz {error.line}: {error.message}
            </li>
          ))}
        </ul>
      ) : null}
      {!summary.saved && summary.changes.length > 0 ? (
        <ul className="max-h-32 space-y-0.5 overflow-y-auto text-xs text-muted-foreground">
          {summary.changes.map((change) => (
            <li key={change.line}>
              wiersz {change.line}: {change.name} — {change.fields.join(", ")}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="flex flex-wrap justify-end gap-2">
        <Button size="sm" variant="outline" onClick={onCancel}>
          {summary.saved ? "Zamknij" : "Anuluj"}
        </Button>
        {!summary.saved ? (
          <Button size="sm" onClick={onSave} loading={saving} disabled={nothing}>
            Zapisz
          </Button>
        ) : null}
      </div>
    </section>
  );
}

function AccountsEditor({ row, onDone }: { row: Counterparty; onDone: () => void }) {
  const patch = useCounterpartyPatch();
  const { showToast } = useToast();
  const [form, setForm] = useState({
    symfonia_partner_id: row.symfonia_partner_id ?? "",
    cost_account: row.cost_account ?? "",
    revenue_account: row.revenue_account ?? "",
  });
  const field = (key: keyof typeof form, label: string) => (
    <Input
      aria-label={label}
      placeholder={label}
      value={form[key]}
      onChange={(event) => setForm((current) => ({ ...current, [key]: event.target.value }))}
      className="h-8 w-32 font-mono text-[12.5px]"
    />
  );
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {field("symfonia_partner_id", "ID Symfonii")}
      {field("cost_account", "Konto kosztowe")}
      {field("revenue_account", "Konto przychodowe")}
      <Button
        size="sm"
        loading={patch.isPending}
        onClick={() =>
          patch.mutate(
            { id: row.id, ...form },
            {
              onSuccess: () => {
                showToast("Konta zapisane.", "success");
                onDone();
              },
              onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać kont."), "error"),
            },
          )
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

/** Finanse → „Kontrahenci”: kartoteka z kontami Symfonii (makieta M7). */
export function CounterpartiesTab({ canWrite = true }: { canWrite?: boolean }) {
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [role, setRole] = useState<CounterpartyRole | null>(null);
  const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState<number | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [summary, setSummary] = useState<ImportSummary | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const list = useCounterparties(q, role, offset);
  const importer = useCounterpartyImport();
  const { showToast } = useToast();

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQ(search);
      setOffset(0);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const send = (chosen: File, save: boolean) =>
    importer.mutate(
      { file: chosen, save },
      {
        onSuccess: (result) => {
          setSummary(result);
          if (result.saved) showToast("Kartoteka zapisana.", "success");
        },
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się przeczytać pliku."), "error"),
      },
    );

  const data = list.data;
  const items = data?.items ?? [];
  return (
    <div className="space-y-3" data-help="finance.counterparties">
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Nazwa, NIP, konto, ID Symfonii…"
          aria-label="Szukaj kontrahentów"
          className={cn(CONTROL, "w-64 min-w-0 flex-1 sm:flex-none")}
        />
        <select
          aria-label="Rola"
          value={role ?? ""}
          onChange={(event) => {
            setRole((event.target.value || null) as CounterpartyRole | null);
            setOffset(0);
          }}
          className={CONTROL}
        >
          <option value="">Rola: wszystkie</option>
          {ROLE_ORDER.map((name) => (
            <option key={name} value={name}>
              {ROLE_LABELS[name]}
              {data ? ` (${data.role_counts[name]})` : ""}
            </option>
          ))}
        </select>
        {data ? (
          <span className="text-xs text-muted-foreground">
            {countPl(data.total, "kontrahent", "kontrahentów", "kontrahentów")} · bez konta
            kosztowego: {data.without_account}
          </span>
        ) : null}
        <div className={cn("ml-auto", !canWrite && "hidden")}>
          <input
            ref={input}
            type="file"
            accept=".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
            className="hidden"
            aria-label="Plik kontrahentów z eBI24"
            onChange={(event) => {
              const chosen = event.target.files?.[0] ?? null;
              event.target.value = "";
              if (!chosen) return;
              setFile(chosen);
              send(chosen, false);
            }}
          />
          <Button
            size="sm"
            variant="outline"
            loading={importer.isPending && !importer.variables?.save}
            onClick={() => input.current?.click()}
          >
            Wgraj plik z eBI24
          </Button>
        </div>
      </div>

      {summary ? (
        <ImportPreview
          summary={summary}
          saving={importer.isPending && importer.variables?.save === true}
          onSave={() => file && send(file, true)}
          onCancel={() => {
            setSummary(null);
            setFile(null);
          }}
        />
      ) : null}

      {list.isLoading ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie kartoteki…</p>
      ) : list.isError ? (
        <QueryStateNotice state="error" onRetry={() => list.refetch()} />
      ) : list.isSuccess && items.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          {q || role
            ? "Nikt nie pasuje do wyszukiwania."
            : "Kartoteka jest pusta. Wgraj plik „Partnerzy → Pobierz” z eBI24."}
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-card">
          <Table density="compact" className="table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead className={`${CALM_HEAD} w-[26%]`}>Nazwa</TableHead>
                <TableHead className={`${CALM_HEAD} w-[15%]`}>Identyfikator</TableHead>
                <TableHead className={`${CALM_HEAD} w-[11%]`}>Rola</TableHead>
                <TableHead className={`${CALM_HEAD} w-[34%]`}>ID Symfonii · konta</TableHead>
                <TableHead className={`${CALM_HEAD} w-[14%]`} />
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((row) => (
                <TableRow key={row.id} className={`${CALM_ROW} align-top`}>
                  <TableCell className="min-w-0">
                    <span className="block truncate">{row.name}</span>
                    <span className={cn(CALM_SUBLINE, "truncate")}>
                      {[row.street, [row.postal_code, row.city].filter(Boolean).join(" "), row.country]
                        .filter(Boolean)
                        .join(", ") || row.email || "—"}
                    </span>
                  </TableCell>
                  <TableCell className="min-w-0">
                    <Mono value={row.id_value} />
                    <span className={CALM_SUBLINE}>{row.id_type_label ?? "bez numeru"}</span>
                  </TableCell>
                  <TableCell>
                    <Badge size="sm" variant={ROLE_VARIANT[row.role]}>
                      {row.role_label}
                    </Badge>
                  </TableCell>
                  <TableCell className="min-w-0">
                    {editing === row.id ? (
                      <AccountsEditor row={row} onDone={() => setEditing(null)} />
                    ) : (
                      <span className="flex flex-wrap gap-x-3 gap-y-0.5">
                        <span>
                          <span className="text-xs text-muted-foreground">ID </span>
                          <Mono value={row.symfonia_partner_id} />
                        </span>
                        <span>
                          <span className="text-xs text-muted-foreground">koszt </span>
                          <Mono value={row.cost_account} />
                        </span>
                        <span>
                          <span className="text-xs text-muted-foreground">przychód </span>
                          <Mono value={row.revenue_account} />
                        </span>
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    {editing === row.id || !canWrite ? null : (
                      <Button size="sm" variant="ghost" onClick={() => setEditing(row.id)}>
                        Edytuj konta
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {data && data.total > QUEUE_PAGE ? (
            <div className="flex items-center justify-between gap-3 border-t border-border px-3.5 py-2 text-xs text-muted-foreground">
              <span>
                {offset + 1}–{offset + items.length} z {data.total}
              </span>
              <span className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={offset === 0}
                  onClick={() => setOffset((current) => Math.max(0, current - QUEUE_PAGE))}
                >
                  Poprzednie
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={offset + items.length >= data.total}
                  onClick={() => setOffset((current) => current + QUEUE_PAGE)}
                >
                  Następne
                </Button>
              </span>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
