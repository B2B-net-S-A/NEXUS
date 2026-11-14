"use client";

import { useEffect, useMemo, useState } from "react";
import { Lock } from "lucide-react";

import { QueryStateNotice, StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DOCUMENT_PAGE,
  useApproveDocuments,
  useDocuments,
  type DocStatus,
  type DocType,
  type DocumentCard,
} from "@/lib/api/accounting";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { useAccounting } from "./AccountingShell";
import { DocumentForm } from "./DocumentForm";
import { DocumentPanel } from "./DocumentPanel";
import { datePl, findPeriod, gr } from "./ledger-model";

const KIND_ORDER: DocType[] = ["FVS", "FVZ", "WB", "LP", "AM", "RMK", "VAT", "PK", "BO", "ST"];
const CONTROL = "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";

function readStatus(): DocStatus | null {
  if (typeof window === "undefined") return null;
  const raw = new URLSearchParams(window.location.search).get("status");
  return raw === "draft" || raw === "approved" ? raw : null;
}

export function DocumentsView() {
  const { config, period } = useAccounting();
  const { showToast } = useToast();
  const { year } = findPeriod(config, period);
  const [scope, setScope] = useState<"month" | "year">("month");
  const [docType, setDocType] = useState<DocType | null>(null);
  const [status, setStatus] = useState<DocStatus | null>(null);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [form, setForm] = useState<{ open: boolean; editing: DocumentCard | null }>({ open: false, editing: null });
  const approve = useApproveDocuments();

  useEffect(() => setStatus(readStatus()), []);
  useEffect(() => {
    setOffset(0);
    setChecked(new Set());
  }, [period.year, period.month, scope, docType, status, search]);

  const filters = useMemo(
    () => ({
      year: period.year,
      month: scope === "month" ? period.month : null,
      docType,
      status,
      q: search,
      offset,
    }),
    [period.year, period.month, scope, docType, status, search, offset],
  );
  const docs = useDocuments(filters, year != null);
  const items = docs.data?.items ?? [];
  const approvable = items.filter((item) => item.can_approve).map((item) => item.id);
  const allOn = approvable.length > 0 && approvable.every((id) => checked.has(id));
  const defaultDate = (() => {
    const month = String(period.month).padStart(2, "0");
    return config.today.startsWith(`${period.year}-${month}`) ? config.today : `${period.year}-${month}-01`;
  })();

  if (!year) {
    return (
      <p className="rounded-lg border border-dashed border-border px-6 py-10 text-center text-sm text-muted-foreground">
        Nie ma roku obrotowego {period.year} — załóż go na zakładce „Miesiąc” albo w Ustawieniach.
      </p>
    );
  }

  const approveChecked = () => {
    const ids = Array.from(checked);
    approve.mutate(ids, {
      onSuccess: (result) => {
        const refused = result.refused.length;
        showToast(
          refused
            ? `Zatwierdzono ${result.approved.length}, odmowa ${refused}: ${result.refused[0].detail}`
            : `Zatwierdzono ${result.approved.length} — pozycje dziennika ${result.approved.map((item) => item.journal_no).join(", ")}.`,
          refused ? "error" : "success",
        );
        setChecked(new Set());
      },
      onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zatwierdzić."), "error"),
    });
  };

  const counts = docs.data?.counts ?? {};
  const total = docs.data?.total ?? 0;
  const shown = offset + items.length;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div role="tablist" aria-label="Rodzaj dokumentu" className="flex flex-wrap gap-1">
          <KindChip active={docType === null} onClick={() => setDocType(null)} label="Wszystkie" count={Object.values(counts).reduce((a, b) => a + (b ?? 0), 0)} />
          {KIND_ORDER.filter((kind) => counts[kind]).map((kind) => (
            <KindChip key={kind} active={docType === kind} onClick={() => setDocType(kind)} label={kind} count={counts[kind] ?? 0} />
          ))}
        </div>
        <select aria-label="Zakres" value={scope} onChange={(e) => setScope(e.target.value as "month" | "year")} className={CONTROL}>
          <option value="month">Wybrany miesiąc</option>
          <option value="year">Cały rok {period.year}</option>
        </select>
        <select
          aria-label="Stan"
          value={status ?? ""}
          onChange={(e) => setStatus((e.target.value || null) as DocStatus | null)}
          className={CONTROL}
        >
          <option value="">Bufor i zatwierdzone</option>
          <option value="draft">Bufor ({docs.data?.drafts ?? 0})</option>
          <option value="approved">Zatwierdzone</option>
        </select>
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Numer, kontrahent, opis…"
          aria-label="Szukaj dokumentów"
          className={cn(CONTROL, "w-52")}
        />
        <div className="ml-auto flex gap-2">
          <Button size="sm" variant="outline" onClick={() => setForm({ open: true, editing: null })}>
            Nowe PK
          </Button>
          {config.me.approver ? (
            <Button size="sm" disabled={checked.size === 0} loading={approve.isPending} onClick={approveChecked}>
              {checked.size ? `Zatwierdź zaznaczone (${checked.size})` : "Zatwierdź zaznaczone"}
            </Button>
          ) : null}
        </div>
      </div>

      <div className={cn("grid gap-3", selectedId != null && "xl:grid-cols-[minmax(0,1fr)_420px]")}>
        <div className="min-w-0">
          {docs.isLoading ? (
            <p className="py-6 text-sm text-muted-foreground">Wczytywanie dokumentów…</p>
          ) : docs.isError ? (
            <QueryStateNotice state="error" onRetry={() => docs.refetch()} />
          ) : docs.isSuccess && items.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
              Nie ma dokumentów dla wybranych filtrów. Źródła (faktury, wyciągi, listy płac) podłączą kolejne etapy;
              ręczne PK dodasz przyciskiem „Nowe PK”.
            </div>
          ) : (
            <div className="rounded-lg border border-border bg-card">
              <table className="w-full table-fixed text-sm">
                <thead>
                  <tr className="border-b border-border/70">
                    {config.me.approver ? (
                      <th className="w-9 px-2.5 py-2">
                        <Checkbox
                          aria-label="Zaznacz wszystkie z bufora"
                          checked={allOn}
                          disabled={approvable.length === 0}
                          onCheckedChange={() => setChecked(allOn ? new Set() : new Set(approvable))}
                        />
                      </th>
                    ) : null}
                    <th className={cn(CALM_HEAD, "w-[15%] px-3 py-2 text-left")}>Typ · stan</th>
                    <th className={cn(CALM_HEAD, "w-[25%] px-2 py-2 text-left")}>Dokument · data</th>
                    <th className={cn(CALM_HEAD, "px-2 py-2 text-left")}>Kontrahent · opis</th>
                    <th className={cn(CALM_HEAD, "w-[17%] px-3 py-2 text-right")}>Wn = Ma, zł</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((doc) => (
                    <tr
                      key={doc.id}
                      onClick={() => setSelectedId(doc.id)}
                      className={cn(CALM_ROW, "cursor-pointer align-top hover:bg-muted/40", doc.id === selectedId && "bg-primary/5")}
                    >
                      {config.me.approver ? (
                        <td className="px-2.5 py-1.5" onClick={(event) => event.stopPropagation()}>
                          <Checkbox
                            aria-label={`Zaznacz ${doc.number}`}
                            checked={checked.has(doc.id)}
                            disabled={!doc.can_approve}
                            onCheckedChange={(on) =>
                              setChecked((current) => {
                                const next = new Set(current);
                                if (on) next.add(doc.id);
                                else next.delete(doc.id);
                                return next;
                              })
                            }
                          />
                        </td>
                      ) : null}
                      <td className="px-3 py-1.5">
                        <StatusDot tone={doc.status === "approved" ? "success" : "warning"}>
                          <span className="text-[13px] font-semibold">{doc.doc_type}</span>
                        </StatusDot>
                        <span className={CALM_SUBLINE}>{doc.status === "approved" ? `poz. ${doc.journal_no}` : "bufor"}</span>
                      </td>
                      <td className="min-w-0 px-2 py-1.5">
                        <span className="block truncate font-medium text-primary">{doc.number}</span>
                        <span className={cn(CALM_SUBLINE, "truncate")}>
                          {datePl(doc.op_date)}
                          {doc.currency !== "PLN" ? ` · ${doc.currency}` : ""}
                          {doc.reversed_by_id ? " · storno" : ""}
                        </span>
                      </td>
                      <td className="min-w-0 px-2 py-1.5">
                        {doc.sensitivity === "payroll" ? (
                          <span className="inline-flex items-center gap-1 text-muted-foreground">
                            <Lock className="h-3 w-3" aria-hidden /> Dokument płacowy
                          </span>
                        ) : (
                          <span className="block truncate">{doc.counterparty?.name ?? doc.description ?? "—"}</span>
                        )}
                        <span className={cn(CALM_SUBLINE, "truncate")}>{doc.description || doc.type_label}</span>
                      </td>
                      <td className={cn(CALM_AMOUNT, "px-3 py-1.5")}>{gr(doc.debit_total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {total > DOCUMENT_PAGE ? (
                <div className="flex items-center justify-between gap-3 border-t border-border px-3.5 py-2 text-xs text-muted-foreground">
                  <span>
                    {offset + 1}–{shown} z {total}
                  </span>
                  <span className="flex gap-2">
                    <Button size="sm" variant="outline" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - DOCUMENT_PAGE))}>
                      Poprzednie
                    </Button>
                    <Button size="sm" variant="outline" disabled={shown >= total} onClick={() => setOffset((o) => o + DOCUMENT_PAGE)}>
                      Następne
                    </Button>
                  </span>
                </div>
              ) : null}
            </div>
          )}
        </div>
        {selectedId != null ? (
          <DocumentPanel
            key={selectedId}
            id={selectedId}
            onClose={() => setSelectedId(null)}
            onEdit={(card) => setForm({ open: true, editing: card })}
            onOpenDocument={setSelectedId}
          />
        ) : null}
      </div>
      {form.open ? (
        <DocumentForm
          key={form.editing?.id ?? "new"}
          open={form.open}
          onOpenChange={(open) => setForm((current) => ({ ...current, open }))}
          defaultDate={defaultDate}
          editing={form.editing}
          onSaved={setSelectedId}
        />
      ) : null}
    </div>
  );
}

function KindChip({ active, onClick, label, count }: { active: boolean; onClick: () => void; label: string; count: number }) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-[13px] pointer-coarse:h-10",
        active ? "border-primary bg-primary/10 font-semibold text-primary" : "border-border text-muted-foreground hover:text-foreground",
      )}
    >
      {label}
      <span className="tabular-nums text-muted-foreground">{count}</span>
    </button>
  );
}
