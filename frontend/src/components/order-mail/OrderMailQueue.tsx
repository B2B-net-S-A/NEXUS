"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { Inbox, FileText, Check, X, ExternalLink, Loader2, MailCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmptyState, PageHeader, QueryStateNotice } from "@/components/ds";
import {
  ORDER_MAIL_ACTION_LABEL,
  ORDER_MAIL_OUTCOME_LABEL,
  orderMailApi,
  type OrderMailDocument,
  type OrderMailOutcome,
  type OrderMailSyncStatus,
} from "@/lib/api/orderMail";
import {
  baselineOf,
  checkOutcome,
  formatAge,
  formatLastRunSummary,
  reasonLabel,
  type CheckBaseline,
} from "@/lib/order-mail-sync";

/**
 * Kolejka zamówień z maila.
 *
 * Trzy reguły, które łatwo zgubić:
 *  - awaria NIE MOŻE renderować się jako pustka: gałąź `isError` jest osobna,
 *    a pusty stan wisi na `isSuccess` (przerwa między ponowieniami react-query
 *    ma `isLoading === false` i puste `data`);
 *  - powód z bramki jest treścią ekranu, nie ozdobą — to on mówi, czego szukać;
 *  - kwoty renderują się jako „—", gdy backend je zredagował; front nie decyduje.
 */

const TABS: Array<{ outcome: OrderMailOutcome; label: string }> = [
  { outcome: "needs_review", label: "Do weryfikacji" },
  { outcome: "auto_applied", label: "Zapisane automatycznie" },
  { outcome: "applied", label: "Zapisane ręcznie" },
  { outcome: "unrecognized_client", label: "Nierozpoznane" },
];

const plnFormatter = new Intl.NumberFormat("pl-PL", { style: "currency", currency: "PLN", maximumFractionDigits: 2 });
const formatPLN = (n: number) => plnFormatter.format(n);

function money(value: string | null, unit: string | null): string {
  if (value == null) return "—";
  const n = Number(value);
  const base = Number.isFinite(n) ? formatPLN(n) : value;
  const u = unit === "hour" ? "/h" : unit === "day" ? "/MD" : unit === "month" ? "/mc" : "";
  return `${base}${u}`;
}

function period(a: string | null, b: string | null): string {
  return `${a ?? "—"} – ${b ?? "bezterminowo"}`;
}

export type OrderMailViewState = "loading" | "error" | "ready";

export interface MailboxCheckProps {
  /** `null` = jeszcze nie pobrano (albo błąd — patrz `statusError`). */
  status: OrderMailSyncStatus | null;
  statusError: boolean;
  /** Między kliknięciem a pierwszym `running: true` z serwera. */
  checking: boolean;
  checkError: string | null;
  onCheckNow: () => void;
}

/**
 * Pasek nad kolejką: kiedy skrzynka była sprawdzana, co z tego wyszło i przycisk
 * „Pobierz zamówienia z maila". Liczby dotyczą CAŁEJ skrzynki — kolejka niżej jest
 * zawężona do portfela, więc Delivery Lead może zobaczyć „1 do weryfikacji"
 * i pustą listę; stąd zdanie o zakresie w opisie wyniku.
 */
export function MailboxCheckPanel(p: MailboxCheckProps) {
  const busy = p.checking || Boolean(p.status?.running);
  const last = p.status?.last_completed ?? null;
  const enabled = p.status?.enabled ?? true;
  let title: string;
  let detail: string;
  if (p.statusError) {
    title = "Nie udało się pobrać stanu skrzynki.";
    detail = "Kolejka poniżej działa — nie wiadomo tylko, jak jest świeża.";
  } else if (!p.status) {
    title = "Sprawdzam stan skrzynki…";
    detail = "";
  } else if (!enabled) {
    title = "Pobieranie zamówień z maila jest wyłączone.";
    detail = "Skrzynka nie jest sprawdzana (ORDER_MAIL_INGEST_ENABLED=false).";
  } else if (busy) {
    title = "Sprawdzam skrzynkę zamowienia@…";
    detail = "Nowe wiadomości pojawią się w kolejce po zakończeniu sprawdzania.";
  } else if (last) {
    title = `Skrzynka sprawdzana automatycznie co ${p.status.interval_minutes} min · ostatnio ${formatAge(last.finished_at)} (${reasonLabel(last.reason)})`;
    detail =
      last.status === "error"
        ? `Sprawdzenie nie powiodło się: ${last.error ?? "błąd bez opisu"}`
        : `${formatLastRunSummary(last)}${last.status === "partial" && last.error ? ` · ${last.error}` : ""} — liczby dla całej skrzynki, kolejka pokazuje Twój zakres.`;
  } else {
    title = `Skrzynka sprawdzana automatycznie co ${p.status.interval_minutes} min · jeszcze nie sprawdzana`;
    detail = "Pierwsze sprawdzenie uruchomi się samo albo po kliknięciu przycisku.";
  }
  const interruptedNote =
    p.status?.interrupted && !busy
      ? " Poprzednie sprawdzenie zostało przerwane (restart aplikacji) — następne uruchomi się samo."
      : "";
  return (
    <section
      data-testid="mailbox-check"
      className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card px-4 py-3 text-sm"
    >
      <div className="min-w-0">
        <div className="font-medium">{title}</div>
        <div
          className={"text-muted-foreground " + (last?.status === "error" && !busy ? "text-destructive" : "")}
          role="status"
          aria-live="polite"
          data-testid="mailbox-check-result"
        >
          {detail}
          {interruptedNote}
        </div>
        {p.checkError && <div className="text-destructive">{p.checkError}</div>}
      </div>
      {p.status?.can_trigger && (
        <Button variant="outline" onClick={p.onCheckNow} disabled={busy || !enabled}>
          {busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <MailCheck className="mr-1 h-4 w-4" />}
          Pobierz zamówienia z maila
        </Button>
      )}
    </section>
  );
}

export interface OrderMailQueueViewProps {
  mailbox: MailboxCheckProps;
  outcome: OrderMailOutcome;
  onOutcomeChange: (o: OrderMailOutcome) => void;
  state: OrderMailViewState;
  items: OrderMailDocument[];
  total: number;
  selectedId: number | null;
  onSelect: (id: number) => void;
  onApply: (id: number) => void;
  onDismiss: (id: number) => void;
  onRefreshPlan?: (id: number) => void;
  onRetry: () => void;
  busy: boolean;
  applyError: string | null;
}

/** Warstwa prezentacyjna — harness `/preview/order-mail` renderuje ją z mocków. */
export function OrderMailQueueView(p: OrderMailQueueViewProps) {
  const selected = p.items.find((i) => i.id === p.selectedId) ?? p.items[0] ?? null;
  return (
    <div className="mx-auto max-w-7xl p-6">
      <PageHeader
        eyebrow="Zamówienia"
        title="Zamówienia z maila"
        description="Załączniki ze skrzynki zamowienia@b2bnetwork.pl: rozpoznany klient, osoby, okres i stawka — do potwierdzenia jednym kliknięciem."
      />
      <MailboxCheckPanel {...p.mailbox} />
      <div className="mt-4 flex gap-2" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.outcome}
            role="tab"
            aria-selected={p.outcome === t.outcome}
            onClick={() => p.onOutcomeChange(t.outcome)}
            className={
              "rounded-md px-3 py-1.5 text-sm " +
              (p.outcome === t.outcome ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:bg-accent")
            }
          >
            {t.label}
            {p.outcome === t.outcome && p.state === "ready" ? ` (${p.total})` : ""}
          </button>
        ))}
      </div>

      {p.state === "error" ? (
        <QueryStateNotice state="error" className="mt-6" description="Nie udało się pobrać kolejki." onRetry={p.onRetry} />
      ) : p.state === "loading" ? (
        <div className="mt-6 text-muted-foreground">Ładowanie…</div>
      ) : p.items.length === 0 ? (
        <EmptyState className="mt-6" icon={Inbox} title="Nic do pokazania" description={`Brak dokumentów w stanie „${ORDER_MAIL_OUTCOME_LABEL[p.outcome]}”.`} />
      ) : (
        <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
          <ul className="divide-y rounded-lg border" data-testid="order-mail-list">
            {p.items.map((d) => (
              <li key={d.id}>
                <button
                  onClick={() => p.onSelect(d.id)}
                  className={"w-full px-4 py-3 text-left hover:bg-accent " + (selected?.id === d.id ? "bg-accent" : "")}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{d.client_name ?? "Nierozpoznany klient"}</span>
                    <span className="text-xs text-muted-foreground">{d.received_at?.slice(0, 10) ?? "—"}</span>
                  </div>
                  <div className="truncate text-sm text-muted-foreground">
                    {d.extraction?.title ?? d.attachment_name ?? d.subject ?? "—"} · {d.extraction?.consultant_rows.length ?? 0} os.
                  </div>
                  {d.gate_verdict && (
                    <Badge variant={d.gate_verdict === "auto" ? "success" : "warning"} className="mt-1">
                      {d.gate_verdict === "auto" ? "Automat: pewne" : "Wymaga weryfikacji"}
                    </Badge>
                  )}
                </button>
              </li>
            ))}
          </ul>
          {selected && (
            <Detail doc={selected} onApply={() => p.onApply(selected.id)} onDismiss={() => p.onDismiss(selected.id)} onRefreshPlan={p.onRefreshPlan ? () => p.onRefreshPlan!(selected.id) : undefined} busy={p.busy} applyError={p.applyError} />
          )}
        </div>
      )}
    </div>
  );
}

/** Kontener: react-query + mutacje. Ekran produkcyjny. */
export function OrderMailQueue() {
  const searchParams = useSearchParams();
  const highlighted = Number(searchParams?.get("doc") ?? "") || null;
  const [outcome, setOutcome] = useState<OrderMailOutcome>("needs_review");
  const [selectedId, setSelectedId] = useState<number | null>(highlighted);
  const qc = useQueryClient();

  const list = useQuery({
    queryKey: ["order-mail", "queue", outcome],
    queryFn: async () => (await orderMailApi.listQueue({ outcome, limit: 100 })).data,
  });
  const apply = useMutation({
    mutationFn: (id: number) => orderMailApi.apply(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["order-mail"] }),
  });
  const dismiss = useMutation({
    mutationFn: (id: number) => orderMailApi.dismiss(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["order-mail"] }),
  });
  const refreshPlan = useMutation({
    mutationFn: (id: number) => orderMailApi.refreshPlan(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["order-mail"] }),
  });
  const applyError = refreshPlan.error
    ? errorDetail(refreshPlan.error, "Nie udało się przeliczyć planu")
    : apply.error
    ? String((apply.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Nie udało się zapisać")
    : null;

  // „Pobierz zamówienia z maila": bieg idzie w tle na serwerze, więc po kliknięciu
  // odpytujemy stan co 2 s, aż pojawi się NOWY wynik (znaczniki z serwera, nie
  // zegar przeglądarki — patrz `lib/order-mail-sync.ts`). `baseline` ≠ null =
  // czekamy na wynik naszego kliknięcia.
  const [baseline, setBaseline] = useState<CheckBaseline | null>(null);
  const [checkNotice, setCheckNotice] = useState<string | null>(null);
  const sync = useQuery({
    queryKey: ["order-mail", "sync-status"],
    queryFn: async () => (await orderMailApi.syncStatus()).data,
    refetchInterval: (query) => (baseline || query.state.data?.running ? 2_000 : 60_000),
  });
  const trigger = useMutation({
    mutationFn: () => orderMailApi.triggerSync(),
    onMutate: () => {
      setCheckNotice(null);
      setBaseline(baselineOf(sync.data));
    },
    onSuccess: () => {
      void sync.refetch();
    },
    onError: (error) => {
      // 409 = bieg już trwa (np. planowy) — dołączamy do niego zamiast startować drugi.
      if (httpStatus(error) === 409) {
        void sync.refetch();
        return;
      }
      setBaseline(null);
      setCheckNotice(errorDetail(error, "Nie udało się uruchomić sprawdzenia skrzynki."));
    },
  });
  useEffect(() => {
    if (!baseline || !sync.data) return;
    const outcome = checkOutcome(sync.data, baseline);
    if (outcome === "pending") return;
    setBaseline(null);
    if (outcome === "interrupted") {
      setCheckNotice("Sprawdzanie zostało przerwane (restart aplikacji). Kliknij ponownie.");
    }
    void qc.invalidateQueries({ queryKey: ["order-mail", "queue"] });
  }, [baseline, sync.data, qc]);

  return (
    <OrderMailQueueView
      mailbox={{
        status: sync.data ?? null,
        statusError: sync.isError,
        checking: baseline !== null,
        checkError: checkNotice,
        onCheckNow: () => trigger.mutate(),
      }}
      outcome={outcome}
      onOutcomeChange={(o) => { setOutcome(o); setSelectedId(null); }}
      state={list.isError ? "error" : !list.isSuccess ? "loading" : "ready"}
      items={list.data?.items ?? []}
      total={list.data?.total ?? 0}
      selectedId={selectedId}
      onSelect={setSelectedId}
      onApply={(id) => apply.mutate(id)}
      onDismiss={(id) => dismiss.mutate(id)}
      onRefreshPlan={(id) => refreshPlan.mutate(id)}
      onRetry={() => list.refetch()}
      busy={apply.isPending || dismiss.isPending || refreshPlan.isPending}
      applyError={applyError}
    />
  );
}

function httpStatus(error: unknown): number | undefined {
  return (error as { response?: { status?: number } } | null)?.response?.status;
}

function errorDetail(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } } | null)?.response?.data?.detail;
  return typeof detail === "string" && detail ? detail : fallback;
}

function Detail({ doc, onApply, onDismiss, onRefreshPlan, busy, applyError }: { doc: OrderMailDocument; onApply: () => void; onDismiss: () => void; onRefreshPlan?: () => void; busy: boolean; applyError: string | null }) {
  const ex = doc.extraction;
  return (
    <section className="rounded-lg border p-4" data-testid="order-mail-detail">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{doc.client_name ?? "Nierozpoznany klient"}</h2>
          <p className="text-sm text-muted-foreground">
            {doc.subject ?? "—"} · od {doc.sender_email ?? "—"} · {doc.attachment_name ?? "—"}
          </p>
          <p className="text-xs text-muted-foreground">
            Rozpoznanie: {doc.identification_method ?? "—"} · reguły: {doc.client_policy ?? "brak własnych reguł"}
          </p>
        </div>
        {doc.has_file && (
          <a className="inline-flex items-center gap-1 text-sm underline" href={orderMailApi.fileUrl(doc.id)} target="_blank" rel="noreferrer">
            <FileText className="h-4 w-4" /> PDF <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
        <dt className="text-muted-foreground">Numer zamówienia</dt><dd>{ex?.title ?? "—"}</dd>
        <dt className="text-muted-foreground">Okres dokumentu</dt><dd>{period(ex?.start_date ?? null, ex?.end_date ?? null)}</dd>
      </dl>

      <h3 className="mt-4 text-sm font-semibold">Osoby i plan zapisu</h3>
      <table className="mt-2 w-full text-sm">
        <thead className="text-left text-muted-foreground">
          <tr><th className="py-1">Osoba</th><th>Okres</th><th>Stawka</th><th>Plan</th></tr>
        </thead>
        <tbody>
          {(doc.proposal?.rows ?? []).map((r) => (
            <tr key={r.row_index} className="border-t align-top">
              <td className="py-1 pr-2">{r.row_name}</td>
              <td className="pr-2">{period(r.start_date, r.end_date)}</td>
              <td className="pr-2">
                {money(r.rate_client, r.rate_unit)}
                {ex?.consultant_rows[r.row_index]?.rate_client_gross != null && (
                  <>
                    {" netto"}
                    <div className="text-xs text-muted-foreground">
                      {money(ex.consultant_rows[r.row_index].rate_client_gross ?? null, r.rate_unit)} brutto ÷ 1,23
                    </div>
                  </>
                )}
              </td>
              <td>
                <div>{ORDER_MAIL_ACTION_LABEL[r.action]}</div>
                {r.reasons.map((x) => <div key={x} className="text-xs text-muted-foreground">{x}</div>)}
              </td>
            </tr>
          ))}
          {(doc.proposal?.rows ?? []).length === 0 && (ex?.consultant_rows ?? []).map((r, i) => (
            <tr key={i} className="border-t"><td className="py-1">{r.consultant_name}</td><td>{period(r.start_date, r.end_date)}</td><td>{money(r.rate_client, r.rate_unit)}</td><td className="text-muted-foreground">—</td></tr>
          ))}
        </tbody>
      </table>

      {doc.gate_reasons.length > 0 && (
        <div className="mt-4 rounded-md border border-amber-300/60 bg-amber-50/60 p-3 text-sm dark:bg-amber-950/20" data-testid="gate-reasons">
          <div className="font-medium">Dlaczego do weryfikacji</div>
          <ul className="mt-1 list-disc pl-5">{doc.gate_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        </div>
      )}
      {doc.error && <div className="mt-3 text-sm text-destructive">Błąd: {doc.error}</div>}
      {applyError && <div className="mt-3 text-sm text-destructive">{applyError}</div>}

      {doc.outcome === "needs_review" && (
        <div className="mt-4 flex flex-wrap gap-2">
          {onRefreshPlan && doc.can_apply && doc.has_file && (
            <Button variant="outline" onClick={onRefreshPlan} disabled={busy} title="Sprawdź stawki z PDF i dopasuj osoby do aktualnej listy konsultantów klienta">
              Przelicz plan
            </Button>
          )}
          <Button onClick={onApply} disabled={!doc.can_apply || busy || !(doc.proposal?.rows?.length)} title={doc.can_apply ? undefined : "Zapis wymaga admina albo przypisanego Delivery Leada"}>
            <Check className="mr-1 h-4 w-4" /> Zastosuj
          </Button>
          <Button variant="outline" onClick={onDismiss} disabled={!doc.can_apply || busy}>
            <X className="mr-1 h-4 w-4" /> Odrzuć
          </Button>
        </div>
      )}
      {doc.applied_order_id && (
        <p className="mt-3 text-sm">Zapisane jako zamówienie #{doc.applied_order_id}{doc.applied_at ? ` (${doc.applied_at.slice(0, 16).replace("T", " ")})` : ""}.</p>
      )}
    </section>
  );
}
