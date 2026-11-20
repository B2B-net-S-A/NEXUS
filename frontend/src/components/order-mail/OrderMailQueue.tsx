"use client";

import { useEffect, useRef, useState, type MouseEvent } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, CircleCheck, CircleX, Inbox, Loader2, MailCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { apiErrorMessage } from "@/lib/api-error";
import { EmptyState, QueryStateNotice } from "@/components/ds";
import { StatusDot } from "@/components/ds/StatusDot";
import type { OrderPdfLoader } from "@/components/finance/OrderPdfViewer";
import {
  orderMailApi,
  type OrderMailDocument,
  type OrderMailOutcome,
  type OrderMailSyncStatus,
} from "@/lib/api/orderMail";
import { fetchAuthenticatedBlob } from "@/lib/authenticated-files";
import { baselineOf, checkOutcome, mailboxSentence, plural, type CheckBaseline, type MailboxTone } from "@/lib/order-mail-sync";
import { formatIsoDatePl } from "@/lib/date-pl";
import type { OverlapApplyChoices } from "@/lib/order-mail-overlap";
import { awaitsDecision, checkPoints, pointShortLabel } from "@/lib/order-mail-points";
import { OrderMailDetail, orderMailNumber, POINT_ICON } from "@/components/order-mail/OrderMailDetail";
import {
  RecheckHistoryPanel,
  type OrderMailViewState,
  type RecheckHistoryProps,
} from "@/components/order-mail/OrderMailHistory";

export type { OrderMailViewState, RecheckHistoryProps } from "@/components/order-mail/OrderMailHistory";

/**
 * Kolejka zamówień z maila — podstrona Kontraktów (przebudowa 20.11.2026,
 * wariant A z makiet 19.11): „← Kontrakty”, stan skrzynki jednym zdaniem,
 * zakładki statusów z licznikami, wąska kolejka po lewej i szczegół po prawej
 * (`OrderMailDetail`), historia automatycznych sprawdzeń zwinięta do jednej
 * linii na dole (`OrderMailHistory`). Adres bez zmian: `/contracts?view=order-mail`
 * (linki z powiadomień, `?doc=`).
 *
 * Trzy reguły, które łatwo zgubić:
 *  - awaria NIE MOŻE renderować się jako pustka: gałąź `isError` jest osobna,
 *    a pusty stan wisi na `isSuccess` (przerwa między ponowieniami react-query
 *    ma `isLoading === false` i puste `data`);
 *  - powód z bramki jest treścią ekranu, nie ozdobą — to on mówi, czego szukać;
 *  - kwoty renderują się jako „—”, gdy backend je zredagował; front nie decyduje.
 */

// Podgląd PDF (pdf.js) ładuje się dopiero, gdy jest co pokazać — kolejka bez
// otwartego podglądu nie ciągnie przeglądarki PDF.
const OrderPdfViewer = dynamic(
  () => import("@/components/finance/OrderPdfViewer").then((m) => m.OrderPdfViewer),
  {
    ssr: false,
    loading: () => (
      <p className="flex h-full items-center justify-center text-sm text-muted-foreground">Wczytywanie podglądu…</p>
    ),
  },
);

/** Ten sam plik co przycisk „PDF” — z tokenem, jako blob. */
const loadQueuePdf: OrderPdfLoader = ({ id }) => fetchAuthenticatedBlob(orderMailApi.fileUrl(id));

export const ORDER_MAIL_TABS: Array<{ outcome: OrderMailOutcome; label: string; empty: string }> = [
  {
    outcome: "needs_review",
    label: "Do weryfikacji",
    empty: "Nic nie czeka na weryfikację — każde zamówienie z maila jest zapisane albo odrzucone.",
  },
  { outcome: "auto_applied", label: "Zapisane automatycznie", empty: "Automat nie zapisał jeszcze żadnego zamówienia z maila." },
  { outcome: "applied", label: "Zapisane ręcznie", empty: "Nikt nie zapisał jeszcze zamówienia z maila ręcznie." },
  { outcome: "unrecognized_client", label: "Nierozpoznane", empty: "Każdy mail z zamówieniem trafił do znanego klienta." },
  // Błąd przetwarzania maila. Od 25.09.2026 system ponawia go sam (do 3 razy
  // w ciągu 7 dni), ale wpis, który się nie udał, musi być widoczny — do tego
  // dnia nie było go na żadnej zakładce.
  { outcome: "failed", label: "Nieudane", empty: "Brak nieudanych — każdy załącznik udało się przeczytać." },
];

/**
 * Pusty stan dla Delivery Leada (`scoped`): kolejka jest zawężona do jego
 * portfela, a wpis bez rozpoznanego klienta nie należy do żadnego — „każdy mail
 * trafił do znanego klienta” byłoby wtedy nieprawdą.
 */
const SCOPED_EMPTY: Partial<Record<OrderMailOutcome, string>> = {
  needs_review: "Nic nie czeka na weryfikację w Twoim portfelu klientów.",
  unrecognized_client: "Maile bez rozpoznanego klienta widzą admin i Finanse — nie należą do żadnego portfela.",
};

/** Liczniki, które wymagają uwagi, gdy nie są zerem. */
const WARN_TABS: ReadonlySet<OrderMailOutcome> = new Set(["needs_review", "failed"]);

export type OrderMailTabCounts = Partial<Record<OrderMailOutcome, number | null>>;

export interface MailboxCheckProps {
  /** `null` = jeszcze nie pobrano (albo błąd — patrz `statusError`). */
  status: OrderMailSyncStatus | null;
  statusError: boolean;
  /** Między kliknięciem a pierwszym `running: true` z serwera. */
  checking: boolean;
  checkError: string | null;
  onCheckNow: () => void;
}

const DOT_TONE: Record<MailboxTone, string> = {
  neutral: "bg-muted-foreground/40",
  info: "bg-info",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-destructive",
};

/** „← Kontrakty”: zwykły link (nowa karta działa), a kliknięcie wraca bez wpisu w historii. */
function BackToContracts({ onBack }: { onBack?: () => void }) {
  const handle = (e: MouseEvent<HTMLAnchorElement>) => {
    if (!onBack || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    onBack();
  };
  return (
    <Link
      href="/contracts"
      onClick={handle}
      className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="size-3.5" aria-hidden /> Kontrakty
    </Link>
  );
}

/**
 * Nagłówek: tytuł, „Pobierz zamówienia z maila” i stan skrzynki jednym zdaniem.
 * Liczby w zdaniu dotyczą CAŁEJ skrzynki — kolejka niżej jest zawężona do
 * portfela, więc Delivery Lead może zobaczyć „1 do weryfikacji” i pustą listę.
 */
function OrderMailHeader({
  mailbox,
  forbidden,
  scoped,
  onBack,
}: {
  mailbox: MailboxCheckProps;
  forbidden: boolean;
  scoped: boolean;
  onBack?: () => void;
}) {
  const title = (
    <h1 className="text-[22px] font-semibold leading-7 tracking-tight text-foreground">Zamówienia z maila</h1>
  );
  if (forbidden) {
    return (
      <header className="space-y-1">
        <BackToContracts onBack={onBack} />
        {title}
      </header>
    );
  }
  const busy = mailbox.checking || Boolean(mailbox.status?.running);
  const enabled = mailbox.status?.enabled ?? true;
  const s = mailboxSentence(mailbox.status, { statusError: mailbox.statusError, checking: mailbox.checking, scoped });
  return (
    <header className="space-y-1">
      <BackToContracts onBack={onBack} />
      <div data-testid="mailbox-check" data-help="contracts.order_mail.check" className="space-y-1">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          {title}
          {mailbox.status?.can_trigger ? (
            <Button
              size="sm"
              variant="outline"
              onClick={mailbox.onCheckNow}
              disabled={busy || !enabled}
              title={!enabled ? "Pobieranie zamówień z maila jest wyłączone" : undefined}
            >
              {busy ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <MailCheck className="size-3.5" aria-hidden />}
              Pobierz zamówienia z maila
            </Button>
          ) : null}
        </div>
        <p className="flex items-start gap-2 text-[13px] leading-5 text-muted-foreground">
          <span aria-hidden className={cn("mt-[7px] size-1.5 shrink-0 rounded-full", DOT_TONE[s.tone])} />
          <span className="min-w-0">
            <span className="text-foreground">{s.title}</span>{" "}
            <span
              role="status"
              aria-live="polite"
              data-testid="mailbox-check-result"
              className={s.detailIsError ? "text-destructive" : undefined}
            >
              {s.detail}
            </span>
          </span>
        </p>
        {mailbox.checkError ? <p className="text-[13px] text-destructive">{mailbox.checkError}</p> : null}
      </div>
    </header>
  );
}

function OrderMailTabs({
  outcome,
  onChange,
  counts,
}: {
  outcome: OrderMailOutcome;
  onChange: (o: OrderMailOutcome) => void;
  counts: OrderMailTabCounts;
}) {
  return (
    <nav
      role="tablist"
      aria-label="Stan zamówień z maila"
      className="flex gap-1 overflow-x-auto border-b border-border"
      data-help="contracts.order_mail.tabs"
    >
      {ORDER_MAIL_TABS.map((t) => {
        const active = t.outcome === outcome;
        const count = counts[t.outcome];
        return (
          <button
            key={t.outcome}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(t.outcome)}
            className={cn(
              "-mb-px inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-[13px] transition-colors pointer-coarse:min-h-10",
              active
                ? "border-primary font-semibold text-foreground"
                : "border-transparent font-medium text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
            {count != null ? (
              <span
                className={cn(
                  "rounded-full px-1.5 text-[11px] tabular-nums",
                  WARN_TABS.has(t.outcome) && count > 0
                    ? "bg-warning-muted font-semibold text-warning-muted-foreground"
                    : count === 0
                      ? "text-muted-foreground/60"
                      : "bg-muted text-muted-foreground",
                )}
              >
                {count}
              </span>
            ) : null}
          </button>
        );
      })}
    </nav>
  );
}

/** Druga linia wiersza kolejki: co z tym wpisem (pierwszy punkt, zapis, błąd). */
function QueueItemStatus({ doc }: { doc: OrderMailDocument }) {
  if (doc.applied_order_id) {
    return (
      <span className="mt-1 flex items-center gap-1.5 text-xs text-foreground">
        <CircleCheck className="size-3.5 shrink-0 text-success" aria-hidden />
        Zamówienie #{doc.applied_order_id}
      </span>
    );
  }
  if (doc.outcome === "failed") {
    return (
      <span className="mt-1 flex items-center gap-1.5 text-xs text-destructive">
        <CircleX className="size-3.5 shrink-0" aria-hidden />
        Nie udało się przetworzyć
      </span>
    );
  }
  const points = awaitsDecision(doc) ? checkPoints(doc) : [];
  const first = points[0];
  if (first) {
    const Icon = POINT_ICON[first.kind];
    return (
      <span className="mt-1 flex min-w-0 items-center gap-1.5 text-xs font-medium text-warning-muted-foreground">
        <Icon className="size-3.5 shrink-0" aria-hidden />
        <span className="truncate">{pointShortLabel(first)}</span>
        {points.length > 1 ? (
          <span className="shrink-0 font-normal text-muted-foreground">+{points.length - 1}</span>
        ) : null}
      </span>
    );
  }
  if (doc.gate_verdict === "auto") {
    return (
      <StatusDot tone="success" className="mt-1">
        Automat: pewne
      </StatusDot>
    );
  }
  if (doc.gate_verdict === "review") {
    return (
      <StatusDot tone="warning" className="mt-1">
        Wymaga weryfikacji
      </StatusDot>
    );
  }
  return null;
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
  /** `overlapChoices` — tylko gdy dokument ma wiersz `overlap` z wyborem. */
  onApply: (id: number, overlapChoices?: OverlapApplyChoices) => void;
  onDismiss: (id: number) => void;
  onRefreshPlan?: (id: number) => void;
  onRetry: () => void;
  busy: boolean;
  applyError: string | null;
  recheck: RecheckHistoryProps;
  /**
   * Dokument wskazany w adresie (`?doc=`), którego nie ma na bieżącej liście
   * (inna zakładka, poza limitem) — doczytany po id. `pinnedState` mówi, czy
   * jeszcze się wczytuje, czy go nie ma. Bez tego ekran podstawiał pierwszy
   * dokument z listy z aktywnym „Zastosuj” (audyt 22.09, FE-N03).
   */
  pinnedDoc?: OrderMailDocument | null;
  /** `null` = wybór nie pochodzi z adresu, więc wolno pokazać pierwszy z listy. */
  pinnedState?: "loading" | "missing" | "ready" | null;
  /**
   * Liczniki zakładek (`null` = jeszcze nie wiadomo — liczba się nie pokazuje,
   * nigdy nie udaje zera). Aktywna zakładka bierze świeższe `total` z listy.
   */
  counts?: OrderMailTabCounts;
  /** „← Kontrakty”: powrót do listy kontraktów. Bez niego link po prostu przechodzi. */
  onBack?: () => void;
  /**
   * Źródło bajtów podglądu PDF. Bez niego podglądu nie ma — przycisk „PDF”
   * otwierający plik w nowej karcie zostaje zawsze.
   */
  loadPdf?: OrderPdfLoader;
}

/** Który dokument pokazać w panelu szczegółów (czysta funkcja, FE-N03). */
export function selectOrderMailDocument(
  items: OrderMailDocument[],
  selectedId: number | null,
  pinnedDoc: OrderMailDocument | null | undefined,
  pinnedState: "loading" | "missing" | "ready" | null = null,
): OrderMailDocument | null {
  const listed = selectedId == null ? undefined : items.find((i) => i.id === selectedId);
  if (listed) return listed;
  if (pinnedState == null) return items[0] ?? null;
  // Dokument wskazany w adresie: tylko ON albo nic — nigdy podstawiony inny.
  return pinnedDoc && pinnedDoc.id === selectedId ? pinnedDoc : null;
}

/** Warstwa prezentacyjna — harness `/preview/order-mail` renderuje ją z mocków. */
export function OrderMailQueueView(p: OrderMailQueueViewProps) {
  const selected = selectOrderMailDocument(p.items, p.selectedId, p.pinnedDoc, p.pinnedState ?? null);
  // Na wąskim ekranie szczegóły są POD całą listą — klik w pozycję zmieniał
  // tylko podświetlenie i wyglądał jak „nic się nie dzieje”. Po wyborze z listy
  // przewijamy do szczegółów (tylko gdy naprawdę leżą pod listą i tylko po
  // kliknięciu).
  const scrollToDetail = useRef(false);
  const listRef = useRef<HTMLUListElement>(null);
  const selectedDocId = selected?.id ?? null;
  useEffect(() => {
    if (!scrollToDetail.current || selectedDocId == null) return;
    scrollToDetail.current = false;
    const detail = document.querySelector('[data-testid="order-mail-detail"]');
    const list = listRef.current;
    if (!detail || !list) return;
    const stacked = detail.getBoundingClientRect().top >= list.getBoundingClientRect().bottom - 1;
    if (!stacked) return;
    detail.scrollIntoView?.({ block: "start", behavior: "smooth" });
  }, [selectedDocId]);
  // Podgląd PDF: na szerokim ekranie otwarty od razu (trzecia kolumna), na
  // węższym za przyciskiem „Pokaż podgląd” — pod szczegółami.
  const [previewOpen, setPreviewOpen] = useState(false);
  useEffect(() => {
    if (window.matchMedia?.("(min-width: 1280px)").matches) setPreviewOpen(true);
  }, []);
  const canPreview = Boolean(p.loadPdf && selected?.has_file);
  const showPreview = canPreview && previewOpen;
  const tab = ORDER_MAIL_TABS.find((t) => t.outcome === p.outcome);
  const counts: OrderMailTabCounts = { ...p.counts, ...(p.state === "ready" ? { [p.outcome]: p.total } : {}) };
  const pinnedNotice =
    p.pinnedState != null && p.selectedId != null && !selected ? (
      p.pinnedState === "loading" ? (
        <div className="text-sm text-muted-foreground" data-testid="order-mail-pinned-loading">
          Wczytywanie dokumentu…
        </div>
      ) : (
        <QueryStateNotice
          state="error"
          description={`Nie znaleziono dokumentu #${p.selectedId} albo nie masz do niego dostępu. Wybierz dokument z listy.`}
        />
      )
    ) : null;
  return (
    // Bez limitu szerokości — trzy kolumny (lista, szczegóły, podgląd PDF)
    // potrzebują całego okna.
    <div className="space-y-3">
      <OrderMailHeader
        mailbox={p.mailbox}
        forbidden={p.state === "forbidden"}
        scoped={p.recheck.scoped}
        onBack={p.onBack}
      />
      {p.state === "forbidden" ? (
        <QueryStateNotice
          state="forbidden"
          description="Nie masz dostępu do kolejki zamówień z maila. Poproś administratora o dostęp do sekcji Delivery."
        />
      ) : (
        <>
          <OrderMailTabs outcome={p.outcome} onChange={p.onOutcomeChange} counts={counts} />
          {p.state === "error" ? (
            <QueryStateNotice state="error" description="Nie udało się pobrać kolejki." onRetry={p.onRetry} />
          ) : p.state === "loading" ? (
            <div className="text-sm text-muted-foreground">Ładowanie…</div>
          ) : p.items.length === 0 && !selected && !pinnedNotice ? (
            <EmptyState
              className="rounded-xl border border-border bg-card py-8"
              icon={Inbox}
              title="Nic do pokazania"
              description={(p.recheck.scoped ? SCOPED_EMPTY[p.outcome] : undefined) ?? tab?.empty}
            />
          ) : (
            // Kolumny liczone po szerokości KONTENERA (menu boczne zabiera miejsce):
            // kolejka | szczegół, a od ~1150 px także podgląd PDF obok.
            <div className="@container">
              <div
                className={cn(
                  "grid grid-cols-[minmax(0,1fr)] items-start gap-3 @3xl:grid-cols-[264px_minmax(0,1fr)]",
                  showPreview && "@6xl:grid-cols-[264px_minmax(0,1.15fr)_minmax(0,1fr)]",
                )}
              >
                <ul
                  ref={listRef}
                  className="space-y-0.5 rounded-xl border border-border bg-card p-1.5 shadow-xs @3xl:max-h-[calc(100dvh-13rem)] @3xl:overflow-y-auto"
                  data-testid="order-mail-list"
                  data-tour="order-mail.queue"
                >
                  {p.items.map((d) => {
                    const active = selected?.id === d.id;
                    const number = orderMailNumber(d);
                    const people = d.proposal?.rows?.length || d.extraction?.consultant_rows?.length || 0;
                    return (
                      <li key={d.id}>
                        <button
                          type="button"
                          onClick={() => {
                            scrollToDetail.current = true;
                            p.onSelect(d.id);
                          }}
                          aria-current={active ? "true" : undefined}
                          className={cn(
                            "w-full rounded-lg px-2.5 py-2 text-left transition-colors",
                            active ? "bg-primary/10" : "hover:bg-muted",
                          )}
                        >
                          <span className="flex items-baseline justify-between gap-2">
                            <span className="min-w-0 truncate text-[13px] font-semibold text-foreground">
                              {d.client_name ?? "Nierozpoznany klient"}
                            </span>
                            <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                              {formatIsoDatePl(d.received_at)}
                            </span>
                          </span>
                          <span className="block truncate text-xs text-muted-foreground">
                            {number ?? d.attachment_name ?? d.subject ?? "bez numeru"} ·{" "}
                            {people} {plural(people, "osoba", "osoby", "osób")}
                          </span>
                          <QueueItemStatus doc={d} />
                        </button>
                      </li>
                    );
                  })}
                </ul>
                <div className="min-w-0 space-y-3">
                  {pinnedNotice}
                  {selected ? (
                    <OrderMailDetail
                      key={selected.id}
                      doc={selected}
                      onApply={(choices) => (choices ? p.onApply(selected.id, choices) : p.onApply(selected.id))}
                      onDismiss={() => p.onDismiss(selected.id)}
                      onRefreshPlan={p.onRefreshPlan ? () => p.onRefreshPlan!(selected.id) : undefined}
                      busy={p.busy}
                      applyError={p.applyError}
                      preview={canPreview ? { open: previewOpen, onToggle: () => setPreviewOpen((open) => !open) } : undefined}
                    />
                  ) : null}
                </div>
                {showPreview && selected && p.loadPdf ? (
                  <div
                    className="h-[70dvh] min-h-[420px] min-w-0 @3xl:col-start-2 @6xl:sticky @6xl:top-2 @6xl:col-start-3 @6xl:h-[calc(100dvh-13rem)]"
                    data-testid="order-mail-preview"
                  >
                    <OrderPdfViewer file={{ kind: "order-mail", id: selected.id }} loadPdf={p.loadPdf} />
                  </div>
                ) : null}
              </div>
              {p.total > p.items.length ? (
                <p className="mt-2 text-xs text-muted-foreground">
                  Pokazano {p.items.length} najnowszych z {p.total}.
                </p>
              ) : null}
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
export function OrderMailQueue({ onBack }: { onBack?: () => void } = {}) {
  const searchParams = useSearchParams();
  const highlighted = Number(searchParams?.get("doc") ?? "") || null;
  const [outcome, setOutcome] = useState<OrderMailOutcome>("needs_review");
  const [selectedId, setSelectedId] = useState<number | null>(highlighted);
  const qc = useQueryClient();
  // Efekt po WARTOŚCI `?doc=`: kliknięcie drugiego alertu na tym samym ekranie
  // to miękka nawigacja — inicjalizator `useState` jej nie widzi (FE-N03).
  useEffect(() => {
    if (highlighted != null) setSelectedId(highlighted);
  }, [highlighted]);

  const list = useQuery({
    queryKey: ["order-mail", "queue", outcome],
    queryFn: async () => (await orderMailApi.listQueue({ outcome, limit: 100 })).data,
  });
  // Liczniki zakładek — jedna lekka odpowiedź (`limit: 1`) na stan. Licznik,
  // który się nie wczytał, po prostu się nie pokazuje (bez ponawiania).
  const tabCounts = useQueries({
    queries: ORDER_MAIL_TABS.map((t) => ({
      queryKey: ["order-mail", "tab-count", t.outcome],
      queryFn: async () => (await orderMailApi.listQueue({ outcome: t.outcome, limit: 1 })).data.total,
      staleTime: 60_000,
      retry: false,
    })),
  });
  const counts: OrderMailTabCounts = {};
  ORDER_MAIL_TABS.forEach((t, i) => {
    counts[t.outcome] = tabCounts[i]?.isSuccess ? tabCounts[i].data : null;
  });
  // Przypięty jest wyłącznie dokument z adresu (alert, powiadomienie). Wybór
  // kliknięciem, który zniknął z listy (np. po „Zastosuj”), dalej przechodzi
  // na pierwszy dokument z kolejki.
  const pinTarget = highlighted != null && selectedId === highlighted ? highlighted : null;
  const inList = pinTarget != null && (list.data?.items ?? []).some((i) => i.id === pinTarget);
  // Dokument spoza bieżącej listy (inna zakładka, poza limitem 100) — doczytaj po id.
  const pinned = useQuery({
    queryKey: ["order-mail", "item", pinTarget],
    queryFn: async () => (await orderMailApi.getItem(pinTarget as number)).data,
    enabled: pinTarget != null && list.isSuccess && !inList,
    retry: false,
  });
  const recheck = useQuery({
    queryKey: ["order-mail", "recheck-runs"],
    queryFn: async () => (await orderMailApi.recheckRuns()).data,
  });
  const apply = useMutation({
    mutationFn: ({ id, choices }: { id: number; choices?: OverlapApplyChoices }) => orderMailApi.apply(id, choices),
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
      : dismiss.error
        ? apiErrorMessage(dismiss.error, "Nie udało się odrzucić wpisu")
        : null;

  // „Pobierz zamówienia z maila”: bieg idzie w tle na serwerze, więc po kliknięciu
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
    const result = checkOutcome(sync.data, baseline);
    if (result === "pending") return;
    setBaseline(null);
    if (result === "interrupted") {
      setCheckNotice("Sprawdzanie zostało przerwane (restart aplikacji). Kliknij ponownie.");
    }
    void qc.invalidateQueries({ queryKey: ["order-mail", "queue"] });
    void qc.invalidateQueries({ queryKey: ["order-mail", "tab-count"] });
  }, [baseline, sync.data, qc]);

  return (
    <OrderMailQueueView
      onBack={onBack}
      loadPdf={loadQueuePdf}
      counts={counts}
      mailbox={{
        status: sync.data ?? null,
        statusError: sync.isError,
        checking: baseline !== null,
        checkError: checkNotice,
        onCheckNow: () => trigger.mutate(),
      }}
      outcome={outcome}
      onOutcomeChange={(o) => {
        setOutcome(o);
        setSelectedId(null);
      }}
      state={
        list.isError ? (httpStatus(list.error) === 403 ? "forbidden" : "error") : !list.isSuccess ? "loading" : "ready"
      }
      items={list.data?.items ?? []}
      total={list.data?.total ?? 0}
      selectedId={selectedId}
      onSelect={setSelectedId}
      onApply={(id, choices) => apply.mutate({ id, choices })}
      onDismiss={(id) => dismiss.mutate(id)}
      onRefreshPlan={(id) => refreshPlan.mutate(id)}
      onRetry={() => list.refetch()}
      busy={apply.isPending || dismiss.isPending || refreshPlan.isPending}
      applyError={applyError}
      pinnedDoc={pinned.data ?? null}
      pinnedState={
        pinTarget == null || inList ? null : pinned.isSuccess ? "ready" : pinned.isError ? "missing" : "loading"
      }
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
