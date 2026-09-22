"use client";

import { Fragment, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Inbox, FileText, Check, X, ExternalLink, History, Loader2, MailCheck, UserCog } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { apiErrorMessage } from "@/lib/api-error";
import { Badge } from "@/components/ui/badge";
import { EmptyState, PageHeader, QueryStateNotice } from "@/components/ds";
import {
  ORDER_MAIL_ACTION_LABEL,
  ORDER_MAIL_OUTCOME_LABEL,
  needsPersonDecision,
  orderMailApi,
  orderWindowHref,
  type OrderMailDocument,
  type OrderMailOutcome,
  type OrderMailRecheckEntry,
  type OrderMailRecheckRun,
  type OrderMailRecheckWindow,
  type OrderMailSyncStatus,
} from "@/lib/api/orderMail";
import { openAuthenticatedFile } from "@/lib/authenticated-files";
import {
  baselineOf,
  checkOutcome,
  formatAge,
  formatLastRunSummary,
  errorOutsideReasons,
  reasonLabel,
  withoutExceptionRepr,
  type CheckBaseline,
} from "@/lib/order-mail-sync";
import { formatDateTimePl, formatIsoDatePl } from "@/lib/date-pl";

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
  return `${formatIsoDatePl(a)} – ${b ? formatIsoDatePl(b) : "bezterminowo"}`;
}

// `forbidden` osobno od `error`: odmowa sekcji (np. podgląd admina jako rola
// bez Delivery albo nieaktualny claim) to brak dostępu, nie awaria do ponowienia.
export type OrderMailViewState = "loading" | "error" | "forbidden" | "ready";

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
        : // Wynik OSTATNIEGO sprawdzenia, nie stan kolejki — zakładki niżej
          // liczą bieżące zaległości (UAT B75: „0 do weryfikacji” obok „(2)”).
          `W ostatnim sprawdzeniu: ${formatLastRunSummary(last)}${last.status === "partial" && last.error ? ` · ${last.error}` : ""}. Bieżące zaległości pokazują zakładki kolejki (w Twoim zakresie).`;
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

export interface RecheckHistoryProps {
  runs: OrderMailRecheckRun[];
  state: OrderMailViewState;
  /** Liczby policzone z widocznych wpisów (Delivery Lead widzi swój portfel). */
  scoped: boolean;
  /**
   * Kiedy weryfikacja ostatnio cokolwiek sprawdziła. Wiersz w tabeli powstaje
   * tylko przy zmianie, więc pusta tabela pod aktualnym znacznikiem znaczy
   * „nic nie wymagało zmiany", a nie „to nie działa". Brak wartości (serwer
   * sprzed wdrożenia) → linia się nie renderuje.
   */
  lastCheckedAt?: string | null;
  /** Ile sprawdzeń z rzędu nic nie zmieniło — zdanie „bez zmian". */
  unchangedRuns?: number;
  window?: OrderMailRecheckWindow;
  onRetry: () => void;
}

/**
 * Początek zdania o kadencji — cały, nie sama godzina.
 *
 * Wyrównane godziny znaczą „okno wyłączone", a wklejenie w jedno zdanie
 * fragmentu „całą dobę" po „w godzinach" dawało „w godzinach całą dobę".
 * Serwer sprzed wdrożenia okna nie przysyła pola — i wtedy faktycznie chodzi
 * całą dobę, więc brak wartości ma ten sam wariant co okno wyłączone.
 */
function recheckScheduleSentence(w: OrderMailRecheckWindow | undefined): string {
  if (!w || !w.enabled) return "Co godzinę, całą dobę,";
  const hh = (h: number) => `${String(h).padStart(2, "0")}:00`;
  return `Co godzinę w godzinach ${hh(w.start_hour)}–${hh(w.end_hour)}`;
}

const RECHECK_CATEGORY_LABEL: Record<string, string> = {
  awaiting_contract: "Czeka na podpis umowy",
  config: "Automatyczny zapis wyłączony",
  unrecognized: "Nie rozpoznano klienta",
  other: "Wymaga weryfikacji",
};

function recheckEntryLabel(e: OrderMailRecheckEntry): string {
  return e.order_number ?? (e.people.length ? e.people.join(", ") : `Dokument #${e.document_id}`);
}

/**
 * „Historia automatycznej weryfikacji" — co zrobił każdy godzinowy bieg.
 *
 * Wiersz rozwija się do KONKRETNYCH dokumentów: zaakceptowanych i wstrzymanych
 * z powodem. Sama liczba „3 wstrzymane" nie mówi, czym się zająć.
 *
 * Gałęzie w tej samej kolejności co reszta ekranu: awaria NIE MOŻE renderować
 * się jako pustka, a pusty stan wisi na `isSuccess` — przerwa między
 * ponowieniami react-query ma `isLoading === false` i puste `data`.
 */
export function RecheckHistoryPanel(p: RecheckHistoryProps) {
  const [openRun, setOpenRun] = useState<number | null>(null);
  return (
    <section className="mt-10" data-testid="recheck-history">
      <h2 className="text-lg font-semibold">Historia automatycznej weryfikacji</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        {recheckScheduleSentence(p.window)} system sam próbuje dokończyć
        wstrzymane zamówienia. Wpis w tabeli powstaje tylko wtedy, gdy sprawdzenie coś zmieniło.
        Zamówienie czekające na podpis umowy nowego kontraktora czeka bez limitu czasu i nie
        powiadamia Delivery Leada.
        {p.scoped ? " Liczby dotyczą Twojego portfela klientów." : ""}
      </p>
      {p.lastCheckedAt ? (
        <p
          className="mt-1 text-sm text-muted-foreground"
          data-testid="recheck-last-checked"
          role="status"
        >
          Sprawdzone ostatnio:{" "}
          <span className="font-medium text-foreground">{formatDateTimePl(p.lastCheckedAt)}</span>
          {p.unchangedRuns ? " — bez zmian." : "."}
        </p>
      ) : null}
      {p.state === "error" || p.state === "forbidden" ? (
        <QueryStateNotice
          state={p.state === "forbidden" ? "forbidden" : "error"}
          className="mt-4"
          description="Nie udało się pobrać historii ponownej weryfikacji."
          onRetry={p.state === "error" ? p.onRetry : undefined}
        />
      ) : p.state === "loading" ? (
        <div className="mt-4 text-muted-foreground">Ładowanie…</div>
      ) : p.runs.length === 0 ? (
        <EmptyState
          className="mt-4"
          icon={History}
          title="Brak zmian do pokazania"
          description="Tu trafiają tylko te sprawdzenia, które coś zmieniły — zapisały zamówienie, zmieniły powód wstrzymania albo wysłały kartę Delivery Leadowi."
        />
      ) : (
        <div className="mt-4 overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-4 py-2 text-left font-medium">Data i godzina</th>
                <th className="px-4 py-2 text-right font-medium">Sprawdzonych</th>
                <th className="px-4 py-2 text-right font-medium">Zaakceptowanych</th>
                <th className="px-4 py-2 text-right font-medium">Wstrzymanych</th>
                <th className="px-4 py-2 text-left font-medium">Szczegóły</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {p.runs.map((run) => (
                <Fragment key={run.id}>
                  <tr data-testid="recheck-run">
                    <td className="px-4 py-2">
                      {formatDateTimePl(run.started_at)}
                      <span className="ml-2 text-xs text-muted-foreground">
                        {reasonLabel(run.trigger)}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">{run.checked}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{run.applied}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{run.held}</td>
                    <td className="px-4 py-2">
                      {run.entries.length === 0 ? (
                        <span className="text-muted-foreground">—</span>
                      ) : (
                        <button
                          className="text-primary underline-offset-2 hover:underline"
                          aria-expanded={openRun === run.id}
                          onClick={() => setOpenRun(openRun === run.id ? null : run.id)}
                        >
                          {openRun === run.id ? "Zwiń" : `Pokaż (${run.entries.length})`}
                        </button>
                      )}
                    </td>
                  </tr>
                  {openRun === run.id && (
                    <tr>
                      <td colSpan={5} className="bg-muted/40 px-4 py-3">
                        <ul className="space-y-2" data-testid="recheck-entries">
                          {run.entries.map((e) => (
                            <li key={e.document_id} className="text-sm">
                              <div className="flex flex-wrap items-center gap-2">
                                <Badge variant={e.outcome === "applied" ? "success" : e.outcome === "error" ? "danger" : "warning"}>
                                  {e.outcome === "applied"
                                    ? "Zaakceptowane"
                                    : e.outcome === "error"
                                    ? "Błąd"
                                    : "Wstrzymane"}
                                </Badge>
                                <Link href={`/contracts?view=order-mail&doc=${e.document_id}`} className="font-medium text-primary underline-offset-2 hover:underline">
                                  {recheckEntryLabel(e)}
                                </Link>
                                {e.client_name && (
                                  <span className="text-muted-foreground">{e.client_name}</span>
                                )}
                                {e.category && (
                                  <span className="text-xs text-muted-foreground">
                                    {RECHECK_CATEGORY_LABEL[e.category] ?? e.category}
                                  </span>
                                )}
                              </div>
                              {e.reasons.length > 0 && (
                                <ul className="mt-1 list-disc pl-5 text-muted-foreground">
                                  {e.reasons.map((r, i) => (
                                    <li key={i}>{r}</li>
                                  ))}
                                </ul>
                              )}
                            </li>
                          ))}
                        </ul>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
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
  recheck: RecheckHistoryProps;
}

/** Warstwa prezentacyjna — harness `/preview/order-mail` renderuje ją z mocków. */
export function OrderMailQueueView(p: OrderMailQueueViewProps) {
  const selected = p.items.find((i) => i.id === p.selectedId) ?? p.items[0] ?? null;
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader
        eyebrow="Zamówienia"
        title="Zamówienia z maila"
        description="Załączniki ze skrzynki zamowienia@b2bnetwork.pl: rozpoznany klient, osoby, okres i stawka — do potwierdzenia jednym kliknięciem."
      />
      {p.state === "forbidden" ? (
        <QueryStateNotice
          state="forbidden"
          className="mt-6"
          description="Nie masz dostępu do kolejki zamówień z maila. Poproś administratora o dostęp do sekcji Delivery."
        />
      ) : (
      <>
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
                    <span className="text-xs text-muted-foreground">{formatIsoDatePl(d.received_at)}</span>
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
            <Detail key={selected.id} doc={selected} onApply={() => p.onApply(selected.id)} onDismiss={() => p.onDismiss(selected.id)} onRefreshPlan={p.onRefreshPlan ? () => p.onRefreshPlan!(selected.id) : undefined} busy={p.busy} applyError={p.applyError} />
          )}
        </div>
      )}
      {/* Historia ma WŁASNE zapytanie: awaria kolejki nie może jej chować,
          bo to ona mówi, czy system w ogóle próbuje dokończyć te wpisy. */}
      <RecheckHistoryPanel {...p.recheck} />
      </>
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
  const recheck = useQuery({
    queryKey: ["order-mail", "recheck-runs"],
    queryFn: async () => (await orderMailApi.recheckRuns()).data,
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
    ? apiErrorMessage(apply.error, "Nie udało się zapisać")
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
      state={
        list.isError
          ? httpStatus(list.error) === 403
            ? "forbidden"
            : "error"
          : !list.isSuccess
          ? "loading"
          : "ready"
      }
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
      recheck={{
        runs: recheck.data?.items ?? [],
        scoped: recheck.data?.scoped ?? false,
        lastCheckedAt: recheck.data?.last_checked_at ?? null,
        unchangedRuns: recheck.data?.unchanged_runs ?? 0,
        window: recheck.data?.window,
        state: recheck.isError
          ? httpStatus(recheck.error) === 403
            ? "forbidden"
            : "error"
          : !recheck.isSuccess
          ? "loading"
          : "ready",
        onRetry: () => recheck.refetch(),
      }}
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
  // Osoba nieaktywna/nieznaleziona na zamówieniu MD/kosztowym: decyzja w oknie
  // zamówienia klienta (ten sam mechanizm co przy ręcznym wgraniu PDF-a).
  const personDecision = needsPersonDecision(doc);
  const windowHref = orderWindowHref(doc);
  const [fileError, setFileError] = useState<string | null>(null);
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
          <div className="flex flex-col items-end gap-1">
            {/* Plik idzie z backendu z tokenem (Bearer) i otwiera się jako blob.
                Zwykły `<a href>` wskazywał względny adres na hoście frontendu,
                bez nagłówka autoryzacji — kończył się stroną 404. */}
            <button
              type="button"
              className="inline-flex items-center gap-1 text-sm underline"
              onClick={() => {
                setFileError(null);
                openAuthenticatedFile(
                  orderMailApi.fileUrl(doc.id),
                  "application/pdf",
                  doc.attachment_name ?? `zamowienie-${doc.id}.pdf`,
                ).catch(() => setFileError("Nie udało się otworzyć pliku PDF."));
              }}
            >
              <FileText className="h-4 w-4" /> PDF <ExternalLink className="h-3 w-3" />
            </button>
            {fileError && <span className="text-xs text-destructive">{fileError}</span>}
          </div>
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
                {(r.existing_person_ids?.length ?? 0) > 0 ? (
                  // Plan nadal zakłada szkic, ale domyślną odpowiedzią nie jest
                  // „nowy kontraktor": osoba o tym imieniu i nazwisku JEST
                  // w bazie. Podpowiedź musi być czytelna, nie szara adnotacja.
                  <div data-testid="person-already-in-base">
                    <div className="font-medium text-amber-700 dark:text-amber-400">
                      Osoba jest już w bazie — potwierdź tożsamość
                    </div>
                    {r.reasons.map((x) => (
                      <div key={x} className="text-xs text-amber-700 dark:text-amber-400">{x}</div>
                    ))}
                    <div className="mt-1 text-xs text-muted-foreground">
                      Po potwierdzeniu: {ORDER_MAIL_ACTION_LABEL[r.action]}
                    </div>
                  </div>
                ) : (
                  <>
                    <div>{ORDER_MAIL_ACTION_LABEL[r.action]}</div>
                    {r.reasons.map((x) => <div key={x} className="text-xs text-muted-foreground">{x}</div>)}
                  </>
                )}
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
          <ul className="mt-1 list-disc pl-5">{doc.gate_reasons.map((r) => <li key={r}>{withoutExceptionRepr(r)}</li>)}</ul>
        </div>
      )}
      {(() => {
        // „Błąd:" tylko, gdy mówi coś, czego nie ma w „Dlaczego do weryfikacji" (UAT B49).
        const distinctError = errorOutsideReasons(doc.error, doc.gate_reasons);
        return distinctError ? <div className="mt-3 text-sm text-destructive">Błąd: {distinctError}</div> : null;
      })()}
      {applyError && <div className="mt-3 text-sm text-destructive">{applyError}</div>}

      {personDecision && doc.outcome === "needs_review" && (
        <div role="status" className="mt-4 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm" data-testid="person-decision">
          <div className="font-medium">Osoba do rozstrzygnięcia</div>
          <p className="mt-1 text-muted-foreground">
            Na tym zamówieniu jest osoba bez aktywnej współpracy albo nieznaleziona w systemie.
            Automat jej nie wznowi ani nie założy — w oknie zamówienia klienta zdecydujesz,
            czy zostawić ją jako zapis historyczny, wznowić współpracę, zastąpić inną osobą
            czy usunąć z zamówienia. Okno otworzy się z tym PDF-em.
          </p>
          {windowHref && doc.can_apply && doc.has_file ? (
            <Link href={windowHref} className={cn(buttonVariants(), "mt-2")}>
              <UserCog className="mr-1 h-4 w-4" /> Rozstrzygnij w oknie zamówienia
            </Link>
          ) : null}
        </div>
      )}

      {doc.outcome === "needs_review" && (
        <div className="mt-4 flex flex-wrap gap-2">
          {onRefreshPlan && doc.can_apply && doc.has_file && (
            <Button variant="outline" onClick={onRefreshPlan} disabled={busy} title="Sprawdź stawki z PDF i dopasuj osoby do aktualnej listy konsultantów klienta">
              Przelicz plan
            </Button>
          )}
          <Button
            onClick={onApply}
            disabled={!doc.can_apply || busy || !(doc.proposal?.rows?.length) || personDecision}
            title={
              !doc.can_apply
                ? "Zapis wymaga admina albo przypisanego Delivery Leada"
                : personDecision
                  ? "Osobę z zakończoną współpracą albo nieznalezioną rozstrzygnij w oknie zamówienia"
                  : undefined
            }
          >
            <Check className="mr-1 h-4 w-4" /> Zastosuj
          </Button>
          <Button variant="outline" onClick={onDismiss} disabled={!doc.can_apply || busy}>
            <X className="mr-1 h-4 w-4" /> Odrzuć
          </Button>
        </div>
      )}
      {doc.applied_order_id && (
        <p className="mt-3 text-sm">Zapisane jako zamówienie #{doc.applied_order_id}{doc.applied_at ? ` (${formatDateTimePl(doc.applied_at)})` : ""}.</p>
      )}
      {doc.proposal?.resolved_in_order && (
        <p className="mt-3 text-sm">
          Rozstrzygnięte w oknie zamówienia — zamówienie nr {doc.proposal.resolved_in_order.order_number ?? `#${doc.proposal.resolved_in_order.order_group_id}`}
          {doc.proposal.resolved_in_order.resolved_at ? ` (${formatDateTimePl(doc.proposal.resolved_in_order.resolved_at)})` : ""}.
        </p>
      )}
    </section>
  );
}
