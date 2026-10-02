"use client";

import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Inbox, FileText, Check, X, ExternalLink, Eye, EyeOff, History, Loader2, MailCheck, UserCog } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { apiErrorMessage } from "@/lib/api-error";
import { Badge } from "@/components/ui/badge";
import { EmptyState, QueryStateNotice } from "@/components/ds";
import { StatusDot } from "@/components/ds/StatusDot";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW } from "@/lib/calm-table";
import type { OrderPdfLoader } from "@/components/finance/OrderPdfViewer";
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
import { fetchAuthenticatedBlob, openAuthenticatedFile } from "@/lib/authenticated-files";
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
import { formatMoney } from "@/lib/money";

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

// Podgląd PDF (pdf.js) ładuje się dopiero, gdy jest co pokazać — kolejka bez
// otwartego podglądu nie ciągnie przeglądarki PDF.
const OrderPdfViewer = dynamic(
  () => import("@/components/finance/OrderPdfViewer").then((m) => m.OrderPdfViewer),
  {
    ssr: false,
    loading: () => (
      <p className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Wczytywanie podglądu…
      </p>
    ),
  },
);

/** Ten sam plik co przycisk „PDF” — z tokenem, jako blob. */
const loadQueuePdf: OrderPdfLoader = ({ id }) =>
  fetchAuthenticatedBlob(orderMailApi.fileUrl(id));

/** Nagłówek sekcji w szczegółach wpisu. */
const SECTION_LABEL =
  "text-[10.5px] font-semibold uppercase tracking-[0.06em] text-muted-foreground";

const TABS: Array<{ outcome: OrderMailOutcome; label: string }> = [
  { outcome: "needs_review", label: "Do weryfikacji" },
  { outcome: "auto_applied", label: "Zapisane automatycznie" },
  { outcome: "applied", label: "Zapisane ręcznie" },
  { outcome: "unrecognized_client", label: "Nierozpoznane" },
  // Błąd przetwarzania maila. Od 25.09.2026 system ponawia go sam (do 3 razy
  // w ciągu 7 dni), ale wpis, który się nie udał, musi być widoczny — do tego
  // dnia nie było go na żadnej zakładce.
  { outcome: "failed", label: "Nieudane" },
];

const FAILED_MANUAL_NOTE =
  "Nie będzie ponawiany — wprowadź zamówienie ręcznie w oknie zamówienia klienta i odrzuć wpis.";
// Bez prawa odrzucenia (`can_dismiss` z serwera) zdanie nie każe klikać
// przycisku, którego ta osoba nie ma (np. Finanse bez portfela — runda 3
// audytu 25.09.2026).
const FAILED_MANUAL_NOTE_READ_ONLY =
  "Nie będzie ponawiany — zamówienie trzeba wprowadzić ręcznie w oknie zamówienia klienta; wpis odrzuci admin albo Delivery Lead klienta.";

/**
 * Zdanie o automatycznych ponowieniach wpisu „Nieudane”.
 *
 * „System ponawia sam” tylko wtedy, gdy serwer tak liczy (`failed_retry_pending`:
 * plik jest, wpis młodszy niż 7 dni, mniej niż 3 próby). Do rundy 2 audytu
 * 25.09.2026 zdanie obiecywało ponowienia także wpisom bez pliku i starszym
 * niż 7 dni, których system nigdy już nie weźmie.
 */
export function failedRetryNote(
  doc: Pick<OrderMailDocument, "document_meta" | "failed_retry_pending" | "can_dismiss">,
): string {
  const retry = (doc.document_meta?.failed_retry ?? null) as { attempts?: number } | null;
  const attempts = Number(retry?.attempts ?? 0);
  if (doc.failed_retry_pending === true) {
    return `Przetwarzanie nie powiodło się. System ponawia je sam z zapisanego PDF-a (próba ${attempts} z 3, przez 7 dni od nadejścia maila).`;
  }
  const manual = doc.can_dismiss === true ? FAILED_MANUAL_NOTE : FAILED_MANUAL_NOTE_READ_ONLY;
  if (attempts >= 3) {
    return `System próbował przetworzyć ten dokument ponownie 3 razy bez skutku. ${manual}`;
  }
  return manual;
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
  const failedRun = last?.status === "error" && !busy;
  const dotTone = p.statusError
    ? "bg-warning"
    : !p.status || !enabled
      ? "bg-muted-foreground/40"
      : busy
        ? "bg-info"
        : failedRun
          ? "bg-destructive"
          : "bg-success";
  return (
    // Jedna linia: stan skrzynki, wynik ostatniego biegu i przycisk. Na wąskim
    // ekranie zawija się — bez poziomego przewijania.
    <section
      data-testid="mailbox-check"
      data-help="contracts.order_mail.check"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-border bg-card px-3 py-2 text-xs"
    >
      <div className="flex min-w-0 items-start gap-1.5 font-medium text-foreground">
        <span aria-hidden className={cn("mt-1.5 size-1.5 shrink-0 rounded-full", dotTone)} />
        <span className="min-w-0">{title}</span>
      </div>
      <div
        className={cn("min-w-0", failedRun ? "text-destructive" : "text-muted-foreground")}
        role="status"
        aria-live="polite"
        data-testid="mailbox-check-result"
      >
        {detail}
        {interruptedNote}
      </div>
      {p.checkError && <div className="text-destructive">{p.checkError}</div>}
      {p.status?.can_trigger && (
        <Button
          size="sm"
          variant="outline"
          className="ml-auto"
          onClick={p.onCheckNow}
          disabled={busy || !enabled}
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <MailCheck className="h-3.5 w-3.5" />}
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
    <section
      className="rounded-lg border border-border bg-card px-4 py-3"
      data-testid="recheck-history"
      data-help="contracts.order_mail.history"
    >
      <h2 className="text-sm font-semibold text-foreground">Historia automatycznej weryfikacji</h2>
      <p className="mt-1 max-w-4xl text-xs text-muted-foreground">
        {recheckScheduleSentence(p.window)} system sam próbuje dokończyć
        wstrzymane zamówienia. Wpis w tabeli powstaje tylko wtedy, gdy sprawdzenie coś zmieniło.
        Zamówienie czekające na podpis umowy nowego kontraktora czeka bez limitu czasu i nie
        powiadamia Delivery Leada.
        {p.scoped ? " Liczby dotyczą Twojego portfela klientów." : ""}
      </p>
      {p.lastCheckedAt ? (
        <p
          className="mt-1 text-xs text-muted-foreground"
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
          className="mt-3"
          description="Nie udało się pobrać historii ponownej weryfikacji."
          onRetry={p.state === "error" ? p.onRetry : undefined}
        />
      ) : p.state === "loading" ? (
        <div className="mt-3 text-sm text-muted-foreground">Ładowanie…</div>
      ) : p.runs.length === 0 ? (
        <EmptyState
          className="mt-3"
          icon={History}
          title="Brak zmian do pokazania"
          description="Tu trafiają tylko te sprawdzenia, które coś zmieniły — zapisały zamówienie, zmieniły powód wstrzymania albo wysłały kartę Delivery Leadowi."
        />
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[34rem] text-sm">
            <thead className={CALM_HEAD}>
              <tr className="border-b border-border">
                <th className="px-2 py-2 text-left">Data i godzina</th>
                <th className="px-2 py-2 text-right">Sprawdzonych</th>
                <th className="px-2 py-2 text-right">Zaakceptowanych</th>
                <th className="px-2 py-2 text-right">Wstrzymanych</th>
                <th className="px-2 py-2 text-left">Szczegóły</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {p.runs.map((run) => (
                <Fragment key={run.id}>
                  <tr data-testid="recheck-run">
                    <td className="whitespace-nowrap px-2 py-2 tabular-nums">
                      {formatDateTimePl(run.started_at)}
                      <span className="ml-2 text-xs text-muted-foreground">
                        {reasonLabel(run.trigger)}
                      </span>
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums">{run.checked}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{run.applied}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{run.held}</td>
                    <td className="px-2 py-2">
                      {run.entries.length === 0 ? (
                        <span className={CALM_EMPTY}>—</span>
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
                      <td colSpan={5} className="bg-muted/40 px-3 py-3">
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
  /**
   * Dokument wskazany w adresie (`?doc=`), którego nie ma na bieżącej liście
   * (inna zakładka, poza limitem) — doczytany po id. `pinnedState` mówi, czy
   * jeszcze się wczytuje, czy go nie ma. Bez tego ekran podstawiał pierwszy
   * dokument z listy z aktywnym „Zastosuj" (audyt 22.09, FE-N03).
   */
  pinnedDoc?: OrderMailDocument | null;
  /** `null` = wybór nie pochodzi z adresu, więc wolno pokazać pierwszy z listy. */
  pinnedState?: "loading" | "missing" | "ready" | null;
  /** Przełącznik trybów modułu — pod tytułem, jak w rejestrze i obsłudze. */
  modeTabs?: ReactNode;
  /**
   * Źródło bajtów podglądu PDF (trzecia kolumna). Bez niego podglądu nie ma —
   * przycisk „PDF” otwierający plik w nowej karcie zostaje zawsze.
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
  // tylko podświetlenie i wyglądał jak „nic się nie dzieje". Po wyborze z listy
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
    const stacked =
      detail.getBoundingClientRect().top >= list.getBoundingClientRect().bottom - 1;
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
  const pinnedNotice =
    p.pinnedState != null && p.selectedId != null && !selected ? (
      p.pinnedState === "loading" ? (
        <div className="text-muted-foreground" data-testid="order-mail-pinned-loading">Wczytywanie dokumentu…</div>
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
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <h1 className="text-lg font-semibold text-foreground">Kontrakty</h1>
        <p className="text-xs text-muted-foreground">
          Zamówienia z maila — załączniki ze skrzynki zamowienia@b2bnetwork.pl: rozpoznany klient,
          osoby, okres i stawka do potwierdzenia jednym kliknięciem.
        </p>
      </div>
      {p.modeTabs}
      {p.state === "forbidden" ? (
        <QueryStateNotice
          state="forbidden"
          description="Nie masz dostępu do kolejki zamówień z maila. Poproś administratora o dostęp do sekcji Delivery."
        />
      ) : (
      <>
      <MailboxCheckPanel {...p.mailbox} />
      <div
        className="inline-flex max-w-full flex-wrap gap-0.5 rounded-lg bg-muted p-0.5"
        role="tablist"
        data-help="contracts.order_mail.tabs"
      >
        {TABS.map((t) => (
          <button
            key={t.outcome}
            role="tab"
            aria-selected={p.outcome === t.outcome}
            onClick={() => p.onOutcomeChange(t.outcome)}
            className={
              "inline-flex min-h-7 items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 py-1 text-xs font-medium pointer-coarse:min-h-10 " +
              (p.outcome === t.outcome
                ? "bg-card font-semibold text-foreground shadow-xs"
                : "text-muted-foreground hover:text-foreground")
            }
          >
            {t.label}
            {p.outcome === t.outcome && p.state === "ready" ? ` (${p.total})` : ""}
          </button>
        ))}
      </div>

      {p.state === "error" ? (
        <QueryStateNotice state="error" description="Nie udało się pobrać kolejki." onRetry={p.onRetry} />
      ) : p.state === "loading" ? (
        <div className="text-sm text-muted-foreground">Ładowanie…</div>
      ) : p.items.length === 0 && !selected && !pinnedNotice ? (
        <EmptyState icon={Inbox} title="Nic do pokazania" description={`Brak dokumentów w stanie „${ORDER_MAIL_OUTCOME_LABEL[p.outcome]}”.`} />
      ) : (
        // Kolumny liczone po szerokości KONTENERA (menu boczne zabiera miejsce):
        // lista | szczegóły, a od ~1150 px także podgląd PDF obok.
        <div className="@container">
          <div
            className={cn(
              "grid grid-cols-[minmax(0,1fr)] items-start gap-3 @3xl:grid-cols-[280px_minmax(0,1fr)]",
              showPreview && "@6xl:grid-cols-[280px_minmax(0,1.15fr)_minmax(0,1fr)]",
            )}
          >
            <ul
              ref={listRef}
              className="rounded-lg border border-border bg-card p-1.5 @3xl:max-h-[calc(100dvh-13rem)] @3xl:overflow-y-auto"
              data-testid="order-mail-list"
            >
              {p.items.map((d) => (
                <li key={d.id}>
                  <button
                    onClick={() => {
                      scrollToDetail.current = true;
                      p.onSelect(d.id);
                    }}
                    aria-current={selected?.id === d.id ? "true" : undefined}
                    className={cn(
                      "w-full rounded-md px-2.5 py-2 text-left",
                      selected?.id === d.id ? "bg-primary/10" : "hover:bg-muted",
                    )}
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="min-w-0 truncate text-[13px] font-semibold text-foreground">{d.client_name ?? "Nierozpoznany klient"}</span>
                      <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">{formatIsoDatePl(d.received_at)}</span>
                    </div>
                    <div className="truncate text-xs text-muted-foreground">
                      {d.extraction?.title ?? d.attachment_name ?? d.subject ?? "—"} · {d.extraction?.consultant_rows.length ?? 0} os.
                    </div>
                    {d.gate_verdict &&
                      (d.gate_verdict === "auto" ? (
                        <StatusDot tone="success" className="mt-1">Automat: pewne</StatusDot>
                      ) : (
                        <Badge variant="warning" size="sm" className="mt-1">Wymaga weryfikacji</Badge>
                      ))}
                  </button>
                </li>
              ))}
            </ul>
            <div className="min-w-0 space-y-3">
              {pinnedNotice}
              {selected && (
                <Detail
                  key={selected.id}
                  doc={selected}
                  onApply={() => p.onApply(selected.id)}
                  onDismiss={() => p.onDismiss(selected.id)}
                  onRefreshPlan={p.onRefreshPlan ? () => p.onRefreshPlan!(selected.id) : undefined}
                  busy={p.busy}
                  applyError={p.applyError}
                  preview={
                    canPreview
                      ? { open: previewOpen, onToggle: () => setPreviewOpen((open) => !open) }
                      : undefined
                  }
                />
              )}
            </div>
            {showPreview && selected && p.loadPdf && (
              <div
                className="h-[70dvh] min-h-[420px] min-w-0 @3xl:col-start-2 @6xl:sticky @6xl:top-2 @6xl:col-start-3 @6xl:h-[calc(100dvh-13rem)]"
                data-testid="order-mail-preview"
              >
                <OrderPdfViewer file={{ kind: "order-mail", id: selected.id }} loadPdf={p.loadPdf} />
              </div>
            )}
          </div>
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
export function OrderMailQueue({ modeTabs }: { modeTabs?: ReactNode } = {}) {
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
  // Przypięty jest wyłącznie dokument z adresu (alert, powiadomienie). Wybór
  // kliknięciem, który zniknął z listy (np. po „Zastosuj"), dalej przechodzi
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
      modeTabs={modeTabs}
      loadPdf={loadQueuePdf}
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
      pinnedDoc={pinned.data ?? null}
      pinnedState={
        pinTarget == null || inList
          ? null
          : pinned.isSuccess
          ? "ready"
          : pinned.isError
          ? "missing"
          : "loading"
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

function canDismiss(doc: OrderMailDocument): boolean {
  return doc.can_dismiss === true;
}

function Detail({
  doc,
  onApply,
  onDismiss,
  onRefreshPlan,
  busy,
  applyError,
  preview,
}: {
  doc: OrderMailDocument;
  onApply: () => void;
  onDismiss: () => void;
  onRefreshPlan?: () => void;
  busy: boolean;
  applyError: string | null;
  /** Przełącznik podglądu PDF — tylko gdy jest plik i źródło podglądu. */
  preview?: { open: boolean; onToggle: () => void };
}) {
  const ex = doc.extraction;
  // Osoba nieaktywna/nieznaleziona na zamówieniu MD/kosztowym: decyzja w oknie
  // zamówienia klienta (ten sam mechanizm co przy ręcznym wgraniu PDF-a).
  const personDecision = needsPersonDecision(doc);
  const windowHref = orderWindowHref(doc);
  const [fileError, setFileError] = useState<string | null>(null);
  return (
    <section className="rounded-lg border border-border bg-card" data-testid="order-mail-detail" data-help="contracts.order_mail.detail">
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2 border-b border-border/60 px-4 py-3">
        <div className="min-w-0">
          <h2 className="font-display text-[15px] font-semibold leading-5 text-foreground">{doc.client_name ?? "Nierozpoznany klient"}</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {doc.subject ?? "—"} · od {doc.sender_email ?? "—"} · {doc.attachment_name ?? "—"}
          </p>
          <p className="text-[11px] text-muted-foreground">
            Rozpoznanie: {doc.identification_method ?? "—"} · reguły: {doc.client_policy ?? "brak własnych reguł"}
          </p>
        </div>
        {doc.has_file && (
          <div className="flex flex-col items-end gap-1">
            <div className="flex flex-wrap items-center justify-end gap-1.5">
              {preview && (
                <Button size="sm" variant="ghost" onClick={preview.onToggle} aria-pressed={preview.open}>
                  {preview.open ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                  {preview.open ? "Ukryj podgląd" : "Pokaż podgląd"}
                </Button>
              )}
              {/* Plik idzie z backendu z tokenem (Bearer) i otwiera się jako blob.
                  Zwykły `<a href>` wskazywał względny adres na hoście frontendu,
                  bez nagłówka autoryzacji — kończył się stroną 404. */}
              <button
                type="button"
                className="inline-flex min-h-8 items-center gap-1 rounded-md px-2 text-xs font-medium text-primary hover:bg-primary/10 pointer-coarse:min-h-10"
                onClick={() => {
                  setFileError(null);
                  openAuthenticatedFile(
                    orderMailApi.fileUrl(doc.id),
                    "application/pdf",
                    doc.attachment_name ?? `zamowienie-${doc.id}.pdf`,
                  ).catch(() => setFileError("Nie udało się otworzyć pliku PDF."));
                }}
              >
                <FileText className="h-3.5 w-3.5" /> PDF <ExternalLink className="h-3 w-3" />
              </button>
            </div>
            {fileError && <span className="text-xs text-destructive">{fileError}</span>}
          </div>
        )}
      </div>

      <div className="space-y-4 px-4 py-3">
      <div>
        <h3 className={SECTION_LABEL}>Dokument</h3>
        <dl className="mt-1.5 grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-[9rem_minmax(0,1fr)]">
          <dt className="text-muted-foreground">Numer zamówienia</dt><dd>{ex?.title ?? <span className={CALM_EMPTY}>—</span>}</dd>
          <dt className="text-muted-foreground">Okres dokumentu</dt><dd className="tabular-nums">{period(ex?.start_date ?? null, ex?.end_date ?? null)}</dd>
        </dl>
      </div>

      <div>
      <h3 className={SECTION_LABEL}>Osoby i plan zapisu</h3>
      {/* Cztery kolumny z kwotami (twarda spacja) — na telefonie przewijane
          w bok zamiast wypychać całą sekcję szczegółów. */}
      <div className="mt-1.5 overflow-x-auto">
      <table className="w-full min-w-[420px] text-sm">
        <thead className={CALM_HEAD}>
          <tr className="border-b border-border text-left">
            <th className="py-1.5 pr-2">Osoba</th>
            <th className="py-1.5 pr-2">Okres</th>
            <th className="py-1.5 pr-3 text-right">Stawka</th>
            <th className="py-1.5">Plan</th>
          </tr>
        </thead>
        <tbody>
          {(doc.proposal?.rows ?? []).map((r) => (
            <tr key={r.row_index} className={cn(CALM_ROW, "align-top last:border-b-0")}>
              <td className="py-2 pr-2 font-medium">{r.row_name}</td>
              <td className="py-2 pr-2 tabular-nums">{period(r.start_date, r.end_date)}</td>
              <td className={cn("py-2 pr-3", CALM_AMOUNT)}>
                {/* Waluta z odczytu dokumentu — 110 EUR nie jest „110 zł” (audyt 24.09, S5). */}
                {formatMoney(r.rate_client, ex?.currency, r.rate_unit)}
                {ex?.consultant_rows[r.row_index]?.rate_client_gross != null && (
                  <>
                    {" netto"}
                    <div className="text-xs text-muted-foreground">
                      {formatMoney(ex.consultant_rows[r.row_index].rate_client_gross ?? null, ex.currency, r.rate_unit)} brutto ÷ 1,23
                    </div>
                  </>
                )}
              </td>
              <td className="py-2">
                {(r.existing_person_ids?.length ?? 0) > 0 ? (
                  // Plan nadal zakłada szkic, ale domyślną odpowiedzią nie jest
                  // „nowy kontraktor": osoba o tym imieniu i nazwisku JEST
                  // w bazie. Podpowiedź musi być czytelna, nie szara adnotacja.
                  <div data-testid="person-already-in-base">
                    <div className="font-medium text-warning-muted-foreground">
                      Osoba jest już w bazie — potwierdź tożsamość
                    </div>
                    {r.reasons.map((x) => (
                      <div key={x} className="text-xs text-warning-muted-foreground">{x}</div>
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
            <tr key={i} className={cn(CALM_ROW, "last:border-b-0")}>
              <td className="py-2 pr-2 font-medium">{r.consultant_name}</td>
              <td className="py-2 pr-2 tabular-nums">{period(r.start_date, r.end_date)}</td>
              <td className={cn("py-2 pr-3", CALM_AMOUNT)}>{formatMoney(r.rate_client, ex?.currency, r.rate_unit)}</td>
              <td className={cn("py-2", CALM_EMPTY)}>—</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      </div>

      {doc.gate_reasons.length > 0 && (
        <div className="rounded-md border border-warning/25 bg-warning-muted p-3 text-sm text-warning-muted-foreground" data-testid="gate-reasons">
          <div className="font-medium">Dlaczego do weryfikacji</div>
          <ul className="mt-1 list-disc pl-5">{doc.gate_reasons.map((r) => <li key={r}>{withoutExceptionRepr(r)}</li>)}</ul>
        </div>
      )}
      {(() => {
        // „Błąd:" tylko, gdy mówi coś, czego nie ma w „Dlaczego do weryfikacji" (UAT B49).
        const distinctError = errorOutsideReasons(doc.error, doc.gate_reasons);
        return distinctError ? <div className="text-sm text-destructive">Błąd: {distinctError}</div> : null;
      })()}
      {applyError && <div className="text-sm text-destructive">{applyError}</div>}
      {doc.outcome === "failed" && (
        <p role="status" className="text-sm text-muted-foreground" data-testid="failed-retry-note">
          {failedRetryNote(doc)}
        </p>
      )}

      {personDecision && doc.outcome === "needs_review" && (
        <div role="status" className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm" data-testid="person-decision">
          <div className="font-medium">Osoba do rozstrzygnięcia</div>
          <p className="mt-1 text-muted-foreground">
            Na tym zamówieniu jest osoba bez aktywnej współpracy albo nieznaleziona w systemie.
            Automat jej nie wznowi ani nie założy — w oknie zamówienia klienta zdecydujesz,
            czy zostawić ją jako zapis historyczny, wznowić współpracę, zastąpić inną osobą
            czy usunąć z zamówienia. Okno otworzy się z tym PDF-em.
          </p>
          {windowHref && doc.can_apply && doc.has_file ? (
            <Link href={windowHref} className={cn(buttonVariants({ size: "sm" }), "mt-2")}>
              <UserCog className="h-3.5 w-3.5" /> Rozstrzygnij w oknie zamówienia
            </Link>
          ) : null}
        </div>
      )}
      {doc.applied_order_id && (
        <p className="text-sm">Zapisane jako zamówienie #{doc.applied_order_id}{doc.applied_at ? ` (${formatDateTimePl(doc.applied_at)})` : ""}.</p>
      )}
      {doc.proposal?.resolved_in_order && (
        <p className="text-sm">
          Rozstrzygnięte w oknie zamówienia — zamówienie nr {doc.proposal.resolved_in_order.order_number ?? `#${doc.proposal.resolved_in_order.order_group_id}`}
          {doc.proposal.resolved_in_order.resolved_at ? ` (${formatDateTimePl(doc.proposal.resolved_in_order.resolved_at)})` : ""}.
        </p>
      )}
      </div>

      {/* Stopka akcji: główna po lewej, „Odrzuć” cicho po prawej. */}
      {doc.outcome === "needs_review" && (
        <div className="flex flex-wrap items-center gap-2 border-t border-border/60 bg-muted/30 px-4 py-2.5">
          <Button
            size="sm"
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
            <Check className="h-3.5 w-3.5" /> Zastosuj
          </Button>
          {onRefreshPlan && doc.can_apply && doc.has_file && (
            <Button size="sm" variant="outline" onClick={onRefreshPlan} disabled={busy} title="Sprawdź stawki z PDF i dopasuj osoby do aktualnej listy konsultantów klienta">
              Przelicz plan
            </Button>
          )}
          <Button size="sm" variant="quiet" className="ml-auto" onClick={onDismiss} disabled={!doc.can_apply || busy}>
            <X className="h-3.5 w-3.5" /> Odrzuć
          </Button>
        </div>
      )}
      {(doc.outcome === "failed" || doc.outcome === "unrecognized_client") && canDismiss(doc) && (
        // Wpis „Nieudane” wprowadzony ręcznie w oknie zamówienia trzeba dać się
        // zdjąć z listy — do rundy 2 audytu 25.09.2026 zakładka tylko rosła.
        // Dokument bez rozpoznanego klienta nie ma czego zastosować, ale też
        // musi dać się zdjąć z kolejki — do 24.09 wisiał w „Nierozpoznane” na
        // zawsze (audyt N2). Bez klienta nie ma przypisanego DL, więc odrzuca admin.
        <div className="flex flex-wrap items-center gap-2 border-t border-border/60 bg-muted/30 px-4 py-2.5">
          <Button size="sm" variant="quiet" className="ml-auto" onClick={onDismiss} disabled={busy}>
            <X className="h-3.5 w-3.5" /> Odrzuć
          </Button>
        </div>
      )}
    </section>
  );
}
