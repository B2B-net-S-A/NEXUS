"use client";

import { useEffect, useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ComparisonPill } from "@/components/hr/approvals/settlement-format";
import { moneyPl } from "@/components/hr/approvals/approvals-format";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useAddFixedSeller,
  useCloseDocument,
  useExpensesSummary,
  useExpensesToSettle,
  useFixedSellers,
  useInvoiceQueue,
  useOpenRequests,
  usePinDocument,
  useRemoveFixedSeller,
  useReopenDocument,
  useSettleDocument,
  useSubscriptions,
  type ExpenseRequestRow,
  type InvoiceQueueState,
} from "@/lib/api/approved-expenses";
import { downloadApprovalDocument, type ApprovalDocument } from "@/lib/api/hr-approvals";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { warsawToday } from "@/lib/warsaw-date";

export const APPROVED_EXPENSES_URL_KEYS = ["expTab"] as const;

type SubTab = "settle" | "subscriptions" | "invoices";
const SUB_TABS: readonly SubTab[] = ["settle", "subscriptions", "invoices"];
const LABEL = "text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground";
const MONTHS = [
  "styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec",
  "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień",
];

function readSubTab(): SubTab {
  if (typeof window === "undefined") return "settle";
  const raw = new URLSearchParams(window.location.search).get("expTab");
  return SUB_TABS.includes(raw as SubTab) ? (raw as SubTab) : "settle";
}

function writeSubTab(next: SubTab) {
  const params = new URLSearchParams(window.location.search);
  if (next === "settle") params.delete("expTab");
  else params.set("expTab", next);
  const query = params.toString();
  window.history.replaceState(null, "", query ? `${window.location.pathname}?${query}` : window.location.pathname);
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "warning" }) {
  return (
    <div
      className={cn(
        "rounded-xl border border-border bg-card px-4 py-3",
        tone === "warning" && "border-warning/40 bg-warning-muted/40",
      )}
    >
      <p className={cn("text-xs text-muted-foreground", tone === "warning" && "text-warning-muted-foreground")}>
        {label}
      </p>
      <p className="mt-1 text-xl font-semibold tabular-nums text-foreground">{value}</p>
      {sub ? <p className="text-xs text-muted-foreground">{sub}</p> : null}
    </div>
  );
}

function SettleButton({ doc, over }: { doc: ApprovalDocument; over: boolean }) {
  const settle = useSettleDocument();
  const { showToast } = useToast();
  const [noting, setNoting] = useState(false);
  const [note, setNote] = useState("");
  const send = () =>
    settle.mutate(
      { documentId: doc.id, note: note || null },
      {
        onSuccess: () => showToast("Rozliczone.", "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się rozliczyć."), "error"),
      },
    );
  if (!doc.can_settle) return null;
  const needsNote = over && doc.topup?.status === "rejected";
  if (needsNote && !noting) {
    return (
      <Button size="sm" variant="outline" onClick={() => setNoting(true)}>
        Rozlicz z notatką
      </Button>
    );
  }
  if (needsNote) {
    return (
      <span className="flex flex-wrap items-center gap-2">
        <Input
          aria-label="Notatka do rozliczenia"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          className="h-8 w-56"
          placeholder="Dlaczego mimo odrzuconej dopłaty"
        />
        <Button size="sm" onClick={send} disabled={note.trim().length < 3} loading={settle.isPending}>
          Rozliczone
        </Button>
      </span>
    );
  }
  return (
    <Button size="sm" onClick={send} loading={settle.isPending} disabled={over && doc.topup?.status !== "approved"}>
      Rozliczone
    </Button>
  );
}

function ToSettleTable({ rows }: { rows: ExpenseRequestRow[] }) {
  const { showToast } = useToast();
  if (rows.length === 0) {
    return <p className="p-4 text-sm text-muted-foreground">Nic nie czeka na rozliczenie.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th className="px-3.5 py-2 font-semibold">Zgoda</th>
            <th className="px-3.5 py-2 font-semibold">Dokument</th>
            <th className="px-3.5 py-2 text-right font-semibold">Zgoda</th>
            <th className="px-3.5 py-2 text-right font-semibold">Faktura</th>
            <th className="px-3.5 py-2 font-semibold">Porównanie</th>
            <th className="px-3.5 py-2" />
          </tr>
        </thead>
        <tbody>
          {rows.flatMap((row) =>
            row.documents.map((doc) => {
              const comparison = row.recurrence === "once" ? row.comparison : doc.comparison;
              const over = comparison?.status === "over";
              return (
                <tr key={doc.id} className="border-b border-border/60 align-top">
                  <td className="px-3.5 py-2.5">
                    <p className="font-semibold text-foreground">{row.title}</p>
                    <p className="text-xs text-muted-foreground">
                      {row.kind_label} · {row.requester_name ?? "—"}
                    </p>
                  </td>
                  <td className="px-3.5 py-2.5">
                    <p className="text-foreground">
                      {doc.seller_name ?? "—"}
                      {doc.source === "ksef" ? (
                        <span className="ml-1.5 rounded-full bg-muted px-1.5 text-[11px] text-muted-foreground">KSeF</span>
                      ) : null}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {[doc.invoice_number, doc.issue_date ? formatIsoDatePl(doc.issue_date) : null]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                    {doc.has_file ? (
                      <button
                        type="button"
                        className="text-xs text-primary hover:underline"
                        onClick={() =>
                          downloadApprovalDocument(row.id, doc).catch((err) =>
                            showToast(apiErrorMessage(err, "Nie udało się pobrać pliku."), "error"),
                          )
                        }
                      >
                        Pobierz plik
                      </button>
                    ) : null}
                  </td>
                  <td className="whitespace-nowrap px-3.5 py-2.5 text-right tabular-nums">{row.amount_text}</td>
                  <td className="whitespace-nowrap px-3.5 py-2.5 text-right tabular-nums">
                    {moneyPl(doc.gross_amount, doc.currency)}
                  </td>
                  <td className="px-3.5 py-2.5">
                    {comparison ? <ComparisonPill comparison={comparison} /> : null}
                    {doc.topup ? (
                      <p className="mt-1 text-xs text-muted-foreground">
                        dopłata {moneyPl(doc.topup.amount, doc.currency)}:{" "}
                        {doc.topup.status === "pending" ? "czeka" : doc.topup.status === "approved" ? "zatwierdzona" : "odrzucona"}
                      </p>
                    ) : over ? (
                      <p className="mt-1 text-xs text-warning-muted-foreground">czeka na prośbę o dopłatę</p>
                    ) : null}
                  </td>
                  <td className="px-3.5 py-2.5 text-right">
                    <SettleButton doc={doc} over={over} />
                  </td>
                </tr>
              );
            }),
          )}
        </tbody>
      </table>
    </div>
  );
}

function AwaitingList({ rows }: { rows: ExpenseRequestRow[] }) {
  if (rows.length === 0) return null;
  return (
    <div className="border-t border-border">
      <h3 className={cn(LABEL, "px-3.5 py-2.5")}>Czeka na fakturę · {rows.length}</h3>
      <ul>
        {rows.map((row) => (
          <li key={row.id} className="flex flex-wrap gap-3 border-t border-border/60 px-3.5 py-2 text-sm">
            <span className="min-w-0 flex-1">
              <span className="font-medium text-foreground">{row.title}</span>
              <span className="text-muted-foreground"> · {row.kind_label} · {row.requester_name ?? "—"}</span>
            </span>
            <span className="tabular-nums text-foreground">{row.amount_text}</span>
            {/* Zgoda „raz” nie wygasa (decyzja Artura 22.10.2026) — serwer nie podaje terminu. */}
            {row.expires_on ? (
              <span className="text-xs text-muted-foreground">
                wygasa {formatIsoDatePl(row.expires_on)}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function SettlePanel() {
  const query = useExpensesToSettle();
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: false,
  });
  if (state === "loading") return <p className="p-4 text-sm text-muted-foreground">Wczytywanie…</p>;
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => query.refetch()} />;
  }
  return (
    <>
      <ToSettleTable rows={query.data?.to_settle ?? []} />
      <AwaitingList rows={query.data?.awaiting ?? []} />
    </>
  );
}

function SubscriptionsPanel() {
  const [includeEnded, setIncludeEnded] = useState(false);
  const query = useSubscriptions(includeEnded);
  const rows = query.data ?? [];
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: rows.length === 0,
  });
  if (state === "loading") return <p className="p-4 text-sm text-muted-foreground">Wczytywanie…</p>;
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => query.refetch()} />;
  }
  return (
    <div>
      {state === "empty" ? (
        <p className="p-4 text-sm text-muted-foreground">Rejestr jest pusty — powstaje sam z zatwierdzonych zgód cyklicznych.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="px-3.5 py-2 font-semibold">Subskrypcja</th>
                <th className="px-3.5 py-2 font-semibold">Dział · opiekun</th>
                <th className="px-3.5 py-2 text-right font-semibold">Miesięcznie</th>
                <th className="px-3.5 py-2 font-semibold">Odnowienie</th>
                <th className="px-3.5 py-2 font-semibold">Ostatnia faktura</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className={cn("border-b border-border/60", row.status === "ended" && "text-muted-foreground")}>
                  <td className="px-3.5 py-2.5">
                    <p className="font-semibold">{row.title}</p>
                    <p className="text-xs text-muted-foreground">{row.amount_text}</p>
                  </td>
                  <td className="px-3.5 py-2.5">
                    {[row.department, row.owner_name].filter(Boolean).join(" · ") || "—"}
                  </td>
                  <td className="px-3.5 py-2.5 text-right tabular-nums">{moneyPl(row.monthly, row.currency)}</td>
                  <td className="px-3.5 py-2.5">
                    {row.status === "ended" ? (
                      `zakończona ${row.ended_on ? formatIsoDatePl(row.ended_on) : ""}`
                    ) : row.renews_on ? (
                      <span
                        className={cn(
                          "whitespace-nowrap rounded-full px-2 py-px text-xs font-medium",
                          row.renews_in_days !== null && row.renews_in_days <= 30
                            ? "bg-warning-muted text-warning-muted-foreground"
                            : "bg-muted text-foreground",
                        )}
                      >
                        {row.renews_in_days !== null && row.renews_in_days <= 30
                          ? `za ${row.renews_in_days} dni · rocznie`
                          : formatIsoDatePl(row.renews_on)}
                        {row.renewal_confirmed ? " · potwierdzone" : row.renewal_asked ? " · pytanie wysłane" : ""}
                      </span>
                    ) : (
                      "miesięcznie"
                    )}
                  </td>
                  <td className="px-3.5 py-2.5">
                    {row.last_document ? (
                      <span className="flex flex-wrap items-center gap-1.5">
                        <span className="text-xs text-muted-foreground">
                          {row.last_document.issue_date ? formatIsoDatePl(row.last_document.issue_date) : "—"}
                        </span>
                        {row.last_document.comparison ? <ComparisonPill comparison={row.last_document.comparison} /> : null}
                      </span>
                    ) : (
                      <span className="text-xs text-muted-foreground">jeszcze bez faktury</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3 px-3.5 py-3 text-xs text-muted-foreground">
        <label className="inline-flex items-center gap-1.5">
          <input type="checkbox" checked={includeEnded} onChange={(event) => setIncludeEnded(event.target.checked)} />
          Pokaż zakończone
        </label>
        <span>
          Rejestr powstaje sam z zatwierdzonych zgód cyklicznych. 30 dni przed odnowieniem rocznym opiekun dostaje
          pytanie „czy dalej potrzebne?”, a zatwierdzający — linię w porannym skrócie.
        </span>
      </div>
    </div>
  );
}

function PinPicker({ doc, onDone }: { doc: ApprovalDocument; onDone: () => void }) {
  const [q, setQ] = useState("");
  const options = useOpenRequests(q);
  const pin = usePinDocument();
  const { showToast } = useToast();
  const send = (requestId: number) =>
    pin.mutate(
      { documentId: doc.id, requestId },
      {
        onSuccess: () => {
          showToast("Faktura przypięta do zgody.", "success");
          onDone();
        },
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się przypiąć faktury."), "error"),
      },
    );
  return (
    <div className="space-y-2">
      <Input aria-label="Szukaj zgody po tytule" placeholder="Szukaj zgody po tytule" value={q} onChange={(e) => setQ(e.target.value)} />
      <ul className="max-h-48 overflow-y-auto rounded-md border border-border">
        {(options.data ?? []).map((option) => (
          <li key={option.id}>
            <button
              type="button"
              onClick={() => send(option.id)}
              disabled={pin.isPending}
              className="w-full border-t border-border/60 px-3 py-1.5 text-left text-sm first:border-t-0 hover:bg-muted/50"
            >
              <span className="font-medium">{option.title}</span>
              <span className="text-xs text-muted-foreground"> · {option.kind_label} · {option.requester_name ?? "—"} · {option.amount_text}</span>
            </button>
          </li>
        ))}
        {options.isSuccess && (options.data ?? []).length === 0 ? (
          <li className="px-3 py-1.5 text-xs text-muted-foreground">Brak otwartych zgód z takim tytułem.</li>
        ) : null}
      </ul>
    </div>
  );
}

function InvoiceDetail({ doc, state }: { doc: ApprovalDocument; state: InvoiceQueueState }) {
  const [mode, setMode] = useState<"none" | "pin" | "close">("none");
  const [note, setNote] = useState("");
  const close = useCloseDocument();
  const reopen = useReopenDocument();
  const addFixed = useAddFixedSeller();
  const { showToast } = useToast();
  const pin = usePinDocument();
  const err = (fallback: string) => (error: unknown) => showToast(apiErrorMessage(error, fallback), "error");

  return (
    <div className="space-y-3 rounded-xl border border-border bg-card p-4">
      <div>
        <p className="text-sm font-semibold text-foreground">{doc.seller_name ?? "Sprzedawca"}</p>
        <p className="text-xs text-muted-foreground">
          {[doc.seller_nip ? `NIP ${doc.seller_nip}` : null, doc.invoice_number, doc.issue_date ? formatIsoDatePl(doc.issue_date) : null]
            .filter(Boolean)
            .join(" · ")}
        </p>
        <p className="mt-1 text-sm">
          {moneyPl(doc.gross_amount, doc.currency)} brutto · z KSeF
          {doc.match_reason_label ? <span className="text-muted-foreground"> · {doc.match_reason_label}</span> : null}
        </p>
        {doc.close_note ? <p className="mt-1 text-xs text-muted-foreground">Notatka: {doc.close_note}</p> : null}
      </div>
      {state === "unmatched" && doc.suggestions && doc.suggestions.length > 0 ? (
        <div>
          <p className={LABEL}>Pasuje kwotą</p>
          <ul className="mt-1 space-y-1">
            {doc.suggestions.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-2 text-sm">
                <span className="min-w-0 flex-1">
                  {s.title} <span className="text-xs text-muted-foreground">· {s.kind_label} · {s.amount_text}</span>
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  loading={pin.isPending}
                  onClick={() =>
                    pin.mutate(
                      { documentId: doc.id, requestId: s.id },
                      { onSuccess: () => showToast("Faktura przypięta do zgody.", "success"), onError: err("Nie udało się przypiąć faktury.") },
                    )
                  }
                >
                  Przypnij
                </Button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {state === "dismissed" ? (
        <Button size="sm" variant="outline" loading={reopen.isPending} onClick={() => reopen.mutate(doc.id, { onError: err("Nie udało się przywrócić faktury.") })}>
          Wróć do kolejki
        </Button>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => setMode(mode === "pin" ? "none" : "pin")}>
            Przypnij do zgody
          </Button>
          {state === "unmatched" && doc.seller_nip ? (
            <Button
              size="sm"
              variant="outline"
              loading={addFixed.isPending}
              onClick={() =>
                addFixed.mutate(
                  { sellerNip: doc.seller_nip ?? "" },
                  {
                    onSuccess: (data) => showToast(`Stały koszt — z kolejki zeszło ${data.moved} faktur.`, "success"),
                    onError: err("Nie udało się dodać stałego kosztu."),
                  },
                )
              }
            >
              Stały koszt — bez zgody
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" onClick={() => setMode(mode === "close" ? "none" : "close")}>
            Zamknij z notatką
          </Button>
        </div>
      )}
      {mode === "pin" ? <PinPicker doc={doc} onDone={() => setMode("none")} /> : null}
      {mode === "close" ? (
        <div className="space-y-2">
          <Textarea rows={2} aria-label="Co to za faktura" placeholder="Co to za faktura (np. zwrot, duplikat)" value={note} onChange={(e) => setNote(e.target.value)} />
          <Button
            size="sm"
            disabled={note.trim().length < 3}
            loading={close.isPending}
            onClick={() =>
              close.mutate({ documentId: doc.id, note }, { onSuccess: () => setMode("none"), onError: err("Nie udało się zamknąć faktury.") })
            }
          >
            Zamknij fakturę
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function FixedSellersCard() {
  const sellers = useFixedSellers();
  const remove = useRemoveFixedSeller();
  const { showToast } = useToast();
  const rows = sellers.data ?? [];
  if (!sellers.isSuccess || rows.length === 0) return null;
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <p className="text-sm font-semibold">Stałe koszty bez zgody · {rows.length}</p>
      <ul className="mt-2 space-y-1">
        {rows.map((row) => (
          <li key={row.seller_nip} className="flex items-center gap-2 text-sm">
            <span className="min-w-0 flex-1 truncate">
              {row.seller_name ?? row.seller_nip} <span className="text-xs text-muted-foreground">· NIP {row.seller_nip}</span>
            </span>
            <Button
              size="sm"
              variant="quiet"
              onClick={() =>
                remove.mutate(row.seller_nip, {
                  onError: (error) => showToast(apiErrorMessage(error, "Nie udało się usunąć z listy."), "error"),
                })
              }
            >
              Usuń
            </Button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function InvoicesPanel() {
  const [state, setState] = useState<InvoiceQueueState>("unmatched");
  const query = useInvoiceQueue(state);
  const rows = query.data ?? [];
  const [selected, setSelected] = useState<number | null>(null);
  const current = rows.find((row) => row.id === selected) ?? rows[0];
  const view = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: rows.length === 0,
  });
  return (
    <div className="grid gap-4 p-3.5 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Które faktury">
          {(
            [
              ["unmatched", "Bez zgody"],
              ["fixed_cost", "Stałe koszty"],
              ["dismissed", "Zamknięte"],
            ] as const
          ).map(([key, label]) => (
            <Button key={key} size="sm" variant={state === key ? "secondary" : "ghost"} aria-pressed={state === key} onClick={() => setState(key)}>
              {label}
            </Button>
          ))}
        </div>
        {view === "loading" ? (
          <p className="text-sm text-muted-foreground">Wczytywanie…</p>
        ) : view === "empty" ? (
          <p className="text-sm text-muted-foreground">
            {state === "unmatched" ? "Każda faktura kosztowa z KSeF ma zgodę albo jest stałym kosztem." : "Pusto."}
          </p>
        ) : view === "forbidden" || view === "not_found" || view === "error" ? (
          <QueryStateNotice state={view} onRetry={() => query.refetch()} />
        ) : (
          <ul className="overflow-hidden rounded-lg border border-border">
            {rows.map((row) => (
              <li key={row.id}>
                <button
                  type="button"
                  aria-current={current?.id === row.id ? "true" : undefined}
                  onClick={() => setSelected(row.id)}
                  className={cn(
                    "flex w-full items-center gap-3 border-t border-border/60 px-3 py-2 text-left text-sm first:border-t-0 hover:bg-muted/50",
                    current?.id === row.id && "bg-primary/5",
                  )}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{row.seller_name ?? row.seller_nip}</span>
                    <span className="block text-xs text-muted-foreground">
                      {[row.invoice_number, row.issue_date ? formatIsoDatePl(row.issue_date) : null].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                  <span className="tabular-nums">{moneyPl(row.gross_amount, row.currency)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="space-y-3">
        {current ? <InvoiceDetail key={current.id} doc={current} state={state} /> : null}
        <FixedSellersCard />
      </div>
    </div>
  );
}

export function KindBars({ year, month }: { year: number; month: number }) {
  const summary = useExpensesSummary(year, month);
  const rows = (summary.data?.by_kind ?? []).filter((row) => Number(row.amount) > 0);
  const max = Math.max(1, ...rows.map((row) => Number(row.amount)));
  return (
    <div className="space-y-2.5 rounded-xl border border-border bg-card p-4">
      <p className="text-sm font-semibold first-letter:uppercase">{MONTHS[month - 1]} według rodzaju</p>
      {/* Pusty stan tylko po udanym zapytaniu — błąd pokazuje rodzic nad kaflami. */}
      {!summary.isSuccess ? (
        summary.isPending ? <p className="text-xs text-muted-foreground">Wczytywanie…</p> : null
      ) : rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">W tym miesiącu nic nie zatwierdzono.</p>
      ) : (
        rows.map((row) => (
          <div key={row.kind}>
            <div className="flex justify-between text-[13px]">
              <span>{row.label}</span>
              <b className="tabular-nums">{moneyPl(row.amount)}</b>
            </div>
            <div className="h-2 overflow-hidden rounded bg-muted" aria-hidden>
              <span className="block h-full bg-primary/70" style={{ width: `${(Number(row.amount) / max) * 100}%` }} />
            </div>
          </div>
        ))
      )}
      {summary.data?.other_currency_count ? (
        <p className="text-xs text-muted-foreground">
          + {summary.data.other_currency_count} w innej walucie (bez kursów nie sumujemy)
        </p>
      ) : null}
      <p className="text-xs text-muted-foreground">Premie poza umową tylko sumą — szczegóły w Płacach.</p>
    </div>
  );
}

/**
 * Finanse → „Wydatki ze zgodą” (makieta 5, Zgody etap 3 — 0486): kafle, „Do
 * rozliczenia”, rejestr subskrypcji, „Faktury bez zgody” i suma miesiąca
 * według rodzaju. Premie poza umową tylko sumą (decyzja Artura 20.10.2026).
 */
export function ApprovedExpensesTab() {
  const today = warsawToday();
  const year = Number(today.slice(0, 4));
  const month = Number(today.slice(5, 7));
  const [tab, setTab] = useState<SubTab>("settle");
  useEffect(() => setTab(readSubTab()), []);
  const summary = useExpensesSummary(year, month);
  const data = summary.data;
  const change = (next: SubTab) => {
    setTab(next);
    writeSubTab(next);
  };
  const tabs: { key: SubTab; label: string; count?: number }[] = [
    { key: "settle", label: "Do rozliczenia", count: data?.to_settle_count },
    { key: "subscriptions", label: "Subskrypcje", count: data?.subscriptions_count },
    { key: "invoices", label: "Faktury bez zgody", count: data?.unmatched_count },
  ];
  return (
    <div className="space-y-3.5">
      {summary.isError ? (
        <QueryStateNotice state="error" onRetry={() => summary.refetch()} />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Tile
            label={`Zatwierdzone — ${MONTHS[month - 1]}`}
            value={data ? moneyPl(data.approved_total) : "…"}
            sub={data ? `${data.approved_count} zgód · ${data.bonus_count} premie poza umową` : undefined}
          />
          <Tile
            label="Czeka na fakturę"
            value={data ? `${data.awaiting_count} · ${moneyPl(data.awaiting_total)}` : "…"}
            sub={data?.awaiting_oldest_days != null ? `najstarsza ${data.awaiting_oldest_days} dni` : undefined}
          />
          <Tile
            label="Subskrypcje miesięcznie"
            value={data ? moneyPl(data.subscriptions_monthly) : "…"}
            sub={data ? `${moneyPl(data.subscriptions_yearly)} rocznie · ${data.subscriptions_count} pozycji` : undefined}
          />
          <Tile
            label="Faktury kosztowe bez zgody"
            value={data ? String(data.unmatched_count) : "…"}
            sub="z KSeF, nie pasują do żadnej zgody"
            tone={data && data.unmatched_count > 0 ? "warning" : undefined}
          />
        </div>
      )}

      <div role="tablist" aria-label="Wydatki ze zgodą" className="flex max-w-full gap-0.5 overflow-x-auto border-b border-border">
        {tabs.map((item) => (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={tab === item.key}
            onClick={() => change(item.key)}
            className={cn(
              "-mb-px inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-1.5 text-[13px] pointer-coarse:min-h-10",
              tab === item.key
                ? "border-primary font-semibold text-foreground"
                : "border-transparent font-medium text-muted-foreground hover:text-foreground",
            )}
          >
            {item.label}
            {item.count ? (
              <span className="rounded-full bg-muted px-1.5 text-[11px] font-semibold tabular-nums text-foreground">
                {item.count}
              </span>
            ) : null}
          </button>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-w-0 overflow-hidden rounded-xl border border-border bg-card">
          {tab === "settle" ? <SettlePanel /> : tab === "subscriptions" ? <SubscriptionsPanel /> : <InvoicesPanel />}
        </div>
        <KindBars year={year} month={month} />
      </div>
    </div>
  );
}
