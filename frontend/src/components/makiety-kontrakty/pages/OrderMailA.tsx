"use client";
// A · Zamówienia z maila — „Kolejka i szczegół”. Podstrona Kontraktów
// („← Kontrakty”), stan skrzynki jednym zdaniem bez nazw zmiennych
// środowiskowych, zakładki statusów z licznikami, wąska kolejka po lewej
// i szczegół po prawej: co odczytano (klient, numer, okres, osoby ze stawką
// i planem) oraz „Do sprawdzenia” jako lista punktów z ikoną i podpowiedzią,
// co zrobić — zamiast żółtej ściany tekstu. Historia automatycznych
// sprawdzeń zwinięta do jednej linii na dole. Nic nie zapisuje.
import { useState, type ReactNode } from "react";
import Link from "next/link";
import { useQueries, useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  Check,
  CircleAlert,
  CircleCheck,
  FileText,
  History,
  MailCheck,
  RotateCcw,
  ScanSearch,
  UserPlus,
  Users,
  UserX,
  X,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatDateTimePl, formatIsoDatePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { withoutExceptionRepr } from "@/lib/order-mail-sync";
import {
  ORDER_MAIL_ACTION_LABEL,
  needsPersonDecision,
  orderMailApi,
  type OrderMailDocument,
  type OrderMailLastRun,
  type OrderMailOutcome,
  type OrderMailProposalRow,
  type OrderMailRecheckEntry,
  type OrderMailRecheckRun,
  type OrderMailSyncStatus,
} from "@/lib/api/orderMail";
import { fmtDate, OSOBY, personFromEmail, plural } from "../shared/format";

// ── Dane (GET — te same trasy co dzisiejsza kolejka) ───────────────────────

export const OUTCOME_TABS: { outcome: OrderMailOutcome; label: string; empty: string }[] = [
  {
    outcome: "needs_review",
    label: "Do sprawdzenia",
    empty: "Nic nie czeka na sprawdzenie — każde zamówienie z maila jest zapisane albo odrzucone.",
  },
  { outcome: "auto_applied", label: "Zapisane automatycznie", empty: "Automat nie zapisał jeszcze żadnego zamówienia z maila." },
  { outcome: "applied", label: "Zapisane ręcznie", empty: "Nikt nie zapisał jeszcze zamówienia z maila ręcznie." },
  { outcome: "unrecognized_client", label: "Nierozpoznane", empty: "Każdy mail z zamówieniem trafił do znanego klienta." },
  { outcome: "failed", label: "Nieudane", empty: "Brak nieudanych — każdy załącznik udało się przeczytać." },
];

export type OutcomeCounts = Partial<Record<OrderMailOutcome, number | null>>;

export function useMkOrderMailCounts(): OutcomeCounts {
  const results = useQueries({
    queries: OUTCOME_TABS.map((t) => ({
      queryKey: ["mk-om-count", t.outcome],
      queryFn: () => orderMailApi.listQueue({ outcome: t.outcome, limit: 1 }).then((r) => r.data.total),
    })),
  });
  const counts: OutcomeCounts = {};
  OUTCOME_TABS.forEach((t, i) => {
    counts[t.outcome] = results[i]?.data ?? null;
  });
  return counts;
}

export function useMkOrderMailQueue(outcome: OrderMailOutcome) {
  return useQuery({
    queryKey: ["mk-om-queue", outcome],
    queryFn: () => orderMailApi.listQueue({ outcome, limit: 100 }).then((r) => r.data),
  });
}

export function useMkOrderMailSync() {
  return useQuery({
    queryKey: ["mk-om-sync"],
    queryFn: () => orderMailApi.syncStatus().then((r) => r.data),
  });
}

export function useMkRecheckRuns() {
  return useQuery({
    queryKey: ["mk-om-recheck", 100],
    queryFn: () => orderMailApi.recheckRuns(100).then((r) => r.data),
  });
}

// ── Słowa ──────────────────────────────────────────────────────────────────

export function period(a: string | null | undefined, b: string | null | undefined): string {
  return `${fmtDate(a)} – ${b ? fmtDate(b) : "bezterminowo"}`;
}

/** „17.11” — dzień w strefie przeglądarki (jak reszta dat z godziną). */
export function shortDay(iso: string | null | undefined): string {
  return formatIsoDatePl(iso).slice(0, 5);
}

export function orderNumber(d: OrderMailDocument): string | null {
  return d.extraction?.title ?? d.proposal?.order_number ?? null;
}

export function peopleCount(d: OrderMailDocument): number {
  return d.proposal?.rows?.length || d.extraction?.consultant_rows?.length || 0;
}

const ACTION_LABEL: Partial<Record<OrderMailProposalRow["action"], string>> = {
  new_draft: "Nowy kontraktor — szkic umowy",
  fill_draft: "Uzupełni szkic umowy",
  reactivate: "Powrót po przerwie — nowe zamówienie",
  unchanged: "Już zapisane — dane zgodne",
  revision: "Zmiana istniejącego zamówienia",
  overlap: "Nachodzi na otwarte zamówienie",
  group: "Linia grupy — zapis ręczny",
  skip: "Pominięta",
};

export function actionLabel(a: OrderMailProposalRow["action"]): string {
  return ACTION_LABEL[a] ?? ORDER_MAIL_ACTION_LABEL[a] ?? a;
}

const IDENT_LABEL: Record<string, string> = {
  registry_id: "rozpoznany po numerze rejestrowym z PDF-a",
  marker: "rozpoznany po znaczniku klienta w PDF-ie",
  sender_domain: "rozpoznany po domenie nadawcy",
};

export function identLabel(d: OrderMailDocument): string {
  const how = d.identification_method ? (IDENT_LABEL[d.identification_method] ?? "rozpoznany automatycznie") : "nie rozpoznano";
  return d.client_policy ? `${how} · reguły odczytu: ${d.client_policy}` : how;
}

function lastRunResult(run: OrderMailLastRun): string {
  if (!run.new_messages) return "bez nowych wiadomości";
  const parts = [plural(run.new_messages, ["nowa wiadomość", "nowe wiadomości", "nowych wiadomości"])];
  if (run.auto_applied) parts.push(`${run.auto_applied} zapisane automatycznie`);
  if (run.needs_review) parts.push(`${run.needs_review} do sprawdzenia`);
  return parts.join(", ");
}

/** Stan skrzynki jednym zdaniem — bez nazw zmiennych środowiskowych. */
export function mailboxSentence(
  s: OrderMailSyncStatus | undefined,
  failed: boolean,
): { tone: string; text: string; detail: string | null } {
  if (failed) {
    return {
      tone: "bg-warning",
      text: "Nie udało się sprawdzić stanu skrzynki.",
      detail: "Kolejka niżej działa — nie wiadomo tylko, jak jest świeża.",
    };
  }
  if (!s) return { tone: "bg-muted-foreground/40", text: "Sprawdzam stan skrzynki…", detail: null };
  const last = s.last_completed;
  const lastText = last
    ? `Ostatnie pobranie ${formatDateTimePl(last.finished_at)} — ${lastRunResult(last)}.`
    : "Skrzynka nie była jeszcze sprawdzana.";
  if (!s.enabled) {
    return {
      tone: "bg-muted-foreground/40",
      text: "Skrzynka zamowienia@ nie jest teraz sprawdzana — pobieranie wyłączył administrator.",
      detail: lastText,
    };
  }
  if (s.running) {
    return { tone: "bg-info", text: "Sprawdzam skrzynkę zamowienia@…", detail: "Nowe zamówienia pojawią się w kolejce po zakończeniu." };
  }
  if (last?.status === "error") {
    return { tone: "bg-destructive", text: "Ostatnie sprawdzenie skrzynki nie powiodło się.", detail: last.error ?? null };
  }
  return { tone: "bg-success", text: `Skrzynka zamowienia@ sprawdzana co ${s.interval_minutes} min.`, detail: lastText };
}

// ── „Do sprawdzenia”: powody bramki jako punkty z podpowiedzią ─────────────

export type PointKind = "new_person" | "uncertain" | "no_people" | "namesake" | "return" | "client" | "other";

export interface CheckPoint {
  kind: PointKind;
  title: string;
  details: string[];
  hint: string | null;
  links?: { href: string; label: string }[];
}

export const POINT_ICON: Record<PointKind, LucideIcon> = {
  new_person: UserPlus,
  uncertain: ScanSearch,
  no_people: UserX,
  namesake: Users,
  return: RotateCcw,
  client: CircleAlert,
  other: CircleAlert,
};

export const POINT_SHORT: Record<PointKind, string> = {
  new_person: "Nowa osoba bez umowy",
  uncertain: "Niepewny odczyt PDF",
  no_people: "Nie odczytano osób",
  namesake: "Imiennik w bazie",
  return: "Powrót po przerwie",
  client: "Nie rozpoznano klienta",
  other: "Inna uwaga",
};

const NO_PEOPLE = /^(Brak osób do dopasowania|Dokument bez rozpoznanych osób|Brak niezależnego potwierdzenia)/;

const upperFirst = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const lowerFirst = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);

function quotedNames(texts: string[]): string[] {
  const names = new Set<string>();
  for (const t of texts) for (const m of t.matchAll(/„([^”]+)”/g)) names.add(m[1]);
  return [...names];
}

/**
 * Powody z bramki (`gate_reasons`) jako kilka punktów: każdy z tytułem,
 * szczegółem i podpowiedzią. API nie oddaje kodów powodów, więc makieta
 * rozpoznaje je po treści; docelowo po `gate_reason_codes`.
 */
export function checkPoints(doc: OrderMailDocument): CheckPoint[] {
  const points: CheckPoint[] = [];
  const uncertain: string[] = [];
  const noPeople: string[] = [];
  const rows = doc.proposal?.rows ?? [];
  if (doc.outcome === "unrecognized_client") {
    points.push({
      kind: "client",
      title: "Nie rozpoznano klienta",
      details: doc.identification_reason ? [doc.identification_reason] : [],
      hint: "Dopisz NIP albo regułę rozpoznawania u klienta — system sam spróbuje ponownie. Albo wprowadź zamówienie ręcznie i odrzuć wpis.",
    });
  }
  for (const raw of doc.gate_reasons) {
    const text = withoutExceptionRepr(raw).trim();
    if (/^Odczyt niepewny:/.test(text)) {
      uncertain.push(upperFirst(text.replace(/^Odczyt niepewny:\s*/, "")));
      continue;
    }
    if (NO_PEOPLE.test(text)) {
      noPeople.push(text);
      continue;
    }
    const m = /^„([^”]+)”:\s*([\s\S]*)$/.exec(text);
    const subject = m?.[1] ?? null;
    const body = m?.[2] ?? text;
    const who = subject ?? "Osoba";
    for (const part of body.split(/;\s+/).filter(Boolean)) {
      if (/czeka na podpisaną umowę/.test(part)) {
        points.push({
          kind: "new_person",
          title: `${who} — nowa osoba bez umowy`,
          details: [upperFirst(part.replace(/\s*—\s*zamówienie czeka na podpisaną umowę B2B\.?$/, ""))],
          hint: "Po podpisaniu umowy B2B system sam ponowi zapis. „Zastosuj” teraz założy szkic umowy do uzupełnienia.",
        });
      } else if (/inna osoba o tym imieniu i nazwisku/.test(part)) {
        const row = rows.find((r) => r.row_name === subject) ?? rows[0];
        const links: { href: string; label: string }[] = [];
        if (row?.candidate_id) links.push({ href: `/candidates/${row.candidate_id}`, label: "Osoba z kontraktu" });
        for (const id of row?.existing_person_ids ?? []) links.push({ href: `/candidates/${id}`, label: "Imiennik" });
        points.push({
          kind: "namesake",
          title: `${who} — w bazie jest imiennik`,
          details: [upperFirst(part.replace(/\s*—\s*potwierdź[\s\S]*$/, "").replace(/\s*\(#\d+\)/, ""))],
          hint: "Porównaj obie osoby; jeśli zamówienie dotyczy osoby z kontraktu, kliknij „Zastosuj”.",
          links,
        });
      } else if (/^Powrót po/.test(part)) {
        points.push({
          kind: "return",
          title: `${who} — ${lowerFirst(part)}`,
          details: [],
          hint: "„Zastosuj” założy nowe zamówienie; poprzednie zostaje bez zmian.",
        });
      } else {
        points.push({ kind: "other", title: subject ? `${subject} — ${lowerFirst(part)}` : part, details: [], hint: null });
      }
    }
  }
  if (noPeople.length) {
    points.push({
      kind: "no_people",
      title: "Nie odczytano osób ani stawek",
      details: uncertain.splice(0),
      hint: "Wprowadź zamówienie ręcznie w oknie zamówienia klienta, potem odrzuć ten wpis.",
    });
  }
  if (uncertain.length) {
    const names = quotedNames(uncertain);
    points.push({
      kind: "uncertain",
      title: names.length ? `Niepewny odczyt PDF — ${names.map((n) => `„${n}”`).join(" czy ")}` : "Niepewny odczyt PDF",
      details: uncertain,
      hint: "Porównaj z tabelą osób w PDF-ie; jeśli plan powyżej się zgadza, kliknij „Zastosuj”.",
    });
  }
  return points;
}

interface RecheckMeta {
  attempts?: number;
  last_at?: string;
  category?: string;
}

/** Co robi automat z tym wpisem (`document_meta.recheck`) — jedno zdanie. */
export function recheckLine(doc: OrderMailDocument): string | null {
  if (doc.outcome !== "needs_review" && doc.outcome !== "unrecognized_client") return null;
  const r = (doc.document_meta?.recheck ?? null) as RecheckMeta | null;
  if (!r) return null;
  const n = Number(r.attempts ?? 0);
  const when = r.last_at ? `, ostatnio ${formatDateTimePl(r.last_at)}` : "";
  if (r.category === "awaiting_contract") return "Czeka na podpis umowy — system sprawdza go co godzinę i zapisze sam.";
  if (r.category === "unrecognized") return `System co godzinę próbuje rozpoznać klienta${when}.`;
  if (!n) return null;
  return `Automat sprawdził ten wpis ${plural(n, ["raz", "razy", "razy"])}${when}, i nadal go wstrzymuje — zdecyduj: „Zastosuj” albo „Odrzuć”.`;
}

// ── Klocki wspólne dla A i B ───────────────────────────────────────────────

export const SECTION_LABEL = "text-[10.5px] font-semibold uppercase tracking-[0.06em] text-muted-foreground";

export function OrderMailHead({ status, failed }: { status?: OrderMailSyncStatus; failed: boolean }) {
  const s = mailboxSentence(status, failed);
  const enabled = status?.enabled ?? false;
  return (
    <header className="space-y-1">
      <Link
        href="/contracts"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" aria-hidden />
        Kontrakty
      </Link>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <h1 className="text-[22px] font-semibold leading-7 tracking-tight text-foreground">Zamówienia z maila</h1>
        {status?.can_trigger ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!enabled || status.running}
            title={!enabled ? "Pobieranie z maila jest wyłączone" : undefined}
          >
            <MailCheck className="size-3.5" aria-hidden />
            Pobierz zamówienia z maila
          </Button>
        ) : null}
      </div>
      <p className="flex items-start gap-2 text-[13px] leading-5 text-muted-foreground" role="status">
        <span aria-hidden className={cn("mt-[7px] size-1.5 shrink-0 rounded-full", s.tone)} />
        <span>
          <span className="text-foreground">{s.text}</span>
          {s.detail ? ` ${s.detail}` : ""}
        </span>
      </p>
    </header>
  );
}

export interface TabItem<K extends string> {
  key: K;
  label: string;
  count?: number | null;
  /** Licznik wymagający uwagi (kolejka do sprawdzenia). */
  warn?: boolean;
}

export function TabsBar<K extends string>({
  items,
  value,
  onChange,
}: {
  items: TabItem<K>[];
  value: K;
  onChange: (k: K) => void;
}) {
  return (
    <nav role="tablist" aria-label="Stan zamówień z maila" className="flex gap-1 overflow-x-auto border-b border-border">
      {items.map((t) => {
        const active = t.key === value;
        return (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(t.key)}
            className={cn(
              "-mb-px inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-[13px] transition-colors",
              active
                ? "border-primary font-semibold text-foreground"
                : "border-transparent font-medium text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
            {t.count != null ? (
              <span
                className={cn(
                  "rounded-full px-1.5 text-[11px] tabular-nums",
                  t.warn && t.count > 0
                    ? "bg-warning-muted font-semibold text-warning-muted-foreground"
                    : t.count === 0
                      ? "text-muted-foreground/60"
                      : "bg-muted text-muted-foreground",
                )}
              >
                {t.count}
              </span>
            ) : null}
          </button>
        );
      })}
    </nav>
  );
}

export function outcomeTabItems(counts: OutcomeCounts): TabItem<OrderMailOutcome>[] {
  return OUTCOME_TABS.map((t) => ({
    key: t.outcome,
    label: t.label,
    count: counts[t.outcome] ?? null,
    warn: t.outcome === "needs_review" || t.outcome === "failed",
  }));
}

/**
 * Osoby z planu zapisu: stawka klienta i to, co zrobi „Zastosuj”.
 * `hideSamePeriod` chowa kolumnę okresu, gdy każdy wiersz ma okres dokumentu
 * (stoi już w wierszu kolejki) — w wąskim rozwinięciu tabeli B.
 */
export function PlanTable({ doc, hideSamePeriod = false }: { doc: OrderMailDocument; hideSamePeriod?: boolean }) {
  const ex = doc.extraction;
  const rows = doc.proposal?.rows ?? [];
  const extracted = ex?.consultant_rows ?? [];
  if (rows.length === 0 && extracted.length === 0) {
    return <p className="text-[13px] text-muted-foreground">Z PDF-a nie udało się odczytać żadnej osoby.</p>;
  }
  const docPeriod = period(ex?.start_date, ex?.end_date);
  const showPeriod =
    !hideSamePeriod ||
    [...rows.map((r) => period(r.start_date, r.end_date)), ...extracted.map((r) => period(r.start_date, r.end_date))].some(
      (p) => p !== docPeriod,
    );
  return (
    <table className="w-full text-[13px]">
      <thead>
        <tr className="border-b border-border">
          <th className={cn(CALM_HEAD, "py-1.5 pr-3 text-left")}>Osoba</th>
          {showPeriod ? <th className={cn(CALM_HEAD, "py-1.5 pr-3 text-left")}>Okres</th> : null}
          <th className={cn(CALM_HEAD, "whitespace-nowrap py-1.5 pr-3 text-right")}>Stawka klienta</th>
          <th className={cn(CALM_HEAD, "whitespace-nowrap py-1.5 text-left")}>Po zastosowaniu</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.row_index} className={cn(CALM_ROW, "align-top last:border-b-0")}>
            <td className="whitespace-nowrap py-2 pr-3 font-medium text-foreground">{r.row_name}</td>
            {showPeriod ? (
              <td className="whitespace-nowrap py-2 pr-3 tabular-nums">{period(r.start_date, r.end_date)}</td>
            ) : null}
            <td className={cn(CALM_AMOUNT, "py-2 pr-3")}>
              {formatMoney(r.rate_client, ex?.currency, r.rate_unit)}
              {r.previous_rate_client ? (
                <span className={CALM_SUBLINE}>
                  poprzednio {formatMoney(r.previous_rate_client, r.previous_rate_currency, r.previous_rate_unit)}
                </span>
              ) : null}
            </td>
            <td className="py-2">{actionLabel(r.action)}</td>
          </tr>
        ))}
        {rows.length === 0
          ? extracted.map((r, i) => (
              <tr key={i} className={cn(CALM_ROW, "last:border-b-0")}>
                <td className="whitespace-nowrap py-2 pr-3 font-medium text-foreground">{r.consultant_name}</td>
                {showPeriod ? (
                  <td className="whitespace-nowrap py-2 pr-3 tabular-nums">{period(r.start_date, r.end_date)}</td>
                ) : null}
                <td className={cn(CALM_AMOUNT, "py-2 pr-3")}>{formatMoney(r.rate_client, ex?.currency, r.rate_unit)}</td>
                <td className="py-2 text-muted-foreground">bez planu zapisu</td>
              </tr>
            ))
          : null}
      </tbody>
    </table>
  );
}

function CheckItem({ p }: { p: CheckPoint }) {
  const [open, setOpen] = useState(false);
  const Icon = POINT_ICON[p.kind];
  const collapsible = p.kind === "uncertain" && p.details.length > 1;
  const details = collapsible && !open ? [] : p.details;
  return (
    <li className="flex gap-2.5">
      <span
        aria-hidden
        className="mt-px flex size-6 shrink-0 items-center justify-center rounded-md bg-warning-muted text-warning-muted-foreground"
      >
        <Icon className="size-3.5" />
      </span>
      <div className="min-w-0 flex-1 text-[12.5px] leading-[18px]">
        <p className="text-[13px] font-medium leading-5 text-foreground">{p.title}</p>
        {details.map((d) => (
          <p key={d} className="text-muted-foreground">
            {d}
          </p>
        ))}
        {collapsible ? (
          <button type="button" onClick={() => setOpen((v) => !v)} className="text-primary hover:underline">
            {open ? "Ukryj uwagi odczytu" : `Uwagi odczytu (${p.details.length})`}
          </button>
        ) : null}
        {p.hint ? (
          <p className="mt-0.5 text-muted-foreground">
            <span className="font-medium text-foreground">Co zrobić: </span>
            {p.hint}
          </p>
        ) : null}
        {p.links?.length ? (
          <p className="mt-0.5 flex flex-wrap gap-x-3">
            {p.links.map((l) => (
              <Link key={l.href} href={l.href} className="font-medium text-primary hover:underline">
                {l.label}
              </Link>
            ))}
          </p>
        ) : null}
      </div>
    </li>
  );
}

export function CheckList({ points }: { points: CheckPoint[] }) {
  return (
    <ul className="space-y-3">
      {points.map((p, i) => (
        <CheckItem key={`${p.kind}-${i}`} p={p} />
      ))}
    </ul>
  );
}

// ── Historia automatycznych sprawdzeń ──────────────────────────────────────

const CATEGORY_LABEL: Record<string, string> = {
  awaiting_contract: "czeka na podpis umowy",
  config: "automat wyłączony",
  unrecognized: "nierozpoznany klient",
  other: "do sprawdzenia",
};

/**
 * Co zmienił bieg w porównaniu z poprzednim wierszem historii — zamiast
 * „5 / 0 / 5” w każdym wierszu. Wiersz powstaje tylko przy zmianie odcisku
 * (zapis, nowy albo zdjęty wpis, kategoria, powód, karta dla DL).
 */
export function runChanges(run: OrderMailRecheckRun, older: OrderMailRecheckRun | undefined): string[] {
  const name = (e: OrderMailRecheckEntry) =>
    e.order_number ?? (e.people.length ? e.people.join(", ") : `dokument #${e.document_id}`);
  const before = new Map((older?.entries ?? []).map((e) => [e.document_id, e]));
  const now = new Set(run.entries.map((e) => e.document_id));
  const groups = new Map<string, string[]>();
  const add = (label: string, value: string) => groups.set(label, [...(groups.get(label) ?? []), value]);
  for (const e of run.entries) {
    const prev = before.get(e.document_id);
    if (e.outcome === "applied") add("zapisano", name(e));
    else if (e.outcome === "error") add("błąd przy", name(e));
    else if (older && !prev) add("nowe do sprawdzenia", name(e));
    else if (prev && e.category && prev.category !== e.category)
      add(`zmiana na „${CATEGORY_LABEL[e.category] ?? e.category}”`, name(e));
    else if (prev && prev.reasons.join("|") !== e.reasons.join("|")) add("zmiana powodu", name(e));
    if (e.alerted) add("karta do Delivery Leada", name(e));
  }
  if (older) {
    for (const e of older.entries) {
      if (!now.has(e.document_id) && e.outcome !== "applied") add("zeszło z kolejki", name(e));
    }
  }
  return [...groups.entries()].map(([label, values]) => `${label}: ${[...new Set(values)].join(", ")}`);
}

/**
 * Historia biegów. Wiersze, w których zmienił się wyłącznie stan powiadomień
 * (flaga karty DL wraca do zera w biegu po karcie), są domyślnie zwinięte —
 * to one robiły z historii ścianę „5 / 0 / 5”.
 */
export function RecheckTable({ runs, limit }: { runs: OrderMailRecheckRun[]; limit?: number }) {
  const [all, setAll] = useState(false);
  const [quiet, setQuiet] = useState(false);
  const rows = runs.map((run, idx) => ({
    run,
    changes: runChanges(run, runs[idx + 1]),
    oldest: idx === runs.length - 1 && runs.length > 1,
  }));
  const hidden = rows.filter((r) => !r.oldest && r.changes.length === 0).length;
  const visible = quiet ? rows : rows.filter((r) => r.oldest || r.changes.length > 0);
  const shown = all || !limit ? visible : visible.slice(0, limit);
  return (
    <>
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-border">
            <th className={cn(CALM_HEAD, "w-[150px] py-2 pl-4 pr-3 text-left")}>Kiedy</th>
            <th className={cn(CALM_HEAD, "w-[100px] px-3 py-2 text-right")}>Sprawdzono</th>
            <th className={cn(CALM_HEAD, "w-[90px] px-3 py-2 text-right")}>Zapisano</th>
            <th className={cn(CALM_HEAD, "w-[110px] px-3 py-2 text-right")}>Wstrzymano</th>
            <th className={cn(CALM_HEAD, "py-2 pl-3 pr-4 text-left")}>Co się zmieniło</th>
          </tr>
        </thead>
        <tbody>
          {shown.map(({ run, changes, oldest }) => (
            <tr key={run.id} className={cn(CALM_ROW, "align-top last:border-b-0")}>
              <td className="py-2 pl-4 pr-3 tabular-nums">
                {formatDateTimePl(run.started_at)}
                <span className={CALM_SUBLINE}>{run.trigger === "manual" ? "ręcznie" : "automatycznie"}</span>
              </td>
              <td className={cn(CALM_AMOUNT, "px-3 py-2 text-muted-foreground")}>{run.checked}</td>
              <td
                className={cn(
                  CALM_AMOUNT,
                  "px-3 py-2",
                  run.applied ? "font-semibold text-foreground" : "text-muted-foreground",
                )}
              >
                {run.applied}
              </td>
              <td className={cn(CALM_AMOUNT, "px-3 py-2 text-muted-foreground")}>{run.held}</td>
              <td className="py-2 pl-3 pr-4">
                {oldest ? (
                  <span className="text-muted-foreground">najstarszy wiersz w historii (30 dni)</span>
                ) : changes.length ? (
                  <span className="line-clamp-2" title={changes.join("\n")}>
                    {changes.join(" · ")}
                  </span>
                ) : (
                  <span className="text-muted-foreground">zmienił się tylko stan powiadomień</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {(limit && visible.length > limit) || hidden > 0 ? (
        <div className="flex flex-wrap gap-x-5 border-t border-border/60 px-4 py-1.5">
          {limit && visible.length > limit ? (
            <Button type="button" variant="tertiary" size="sm" className="px-0" onClick={() => setAll((v) => !v)}>
              {all ? "Pokaż tylko najnowsze" : `Pokaż starsze (${visible.length - limit})`}
            </Button>
          ) : null}
          {hidden > 0 ? (
            <Button type="button" variant="tertiary" size="sm" className="px-0" onClick={() => setQuiet((v) => !v)}>
              {quiet
                ? "Ukryj wiersze bez zmian w kolejce"
                : `Pokaż też ${plural(hidden, ["wiersz", "wiersze", "wierszy"])}, w których zmienił się tylko stan powiadomień`}
            </Button>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

export function recheckSummary(data: { last_checked_at?: string | null; unchanged_runs?: number } | undefined): string | null {
  if (!data?.last_checked_at) return null;
  return `${formatDateTimePl(data.last_checked_at)} — ${data.unchanged_runs ? "bez zmian" : "ze zmianą w kolejce"}`;
}

function RecheckFooter() {
  const [open, setOpen] = useState(false);
  const q = useMkRecheckRuns();
  const data = q.data;
  const w = data?.window;
  const hours = w?.enabled ? ` · co godzinę ${w.start_hour}:00–${w.end_hour}:00` : "";
  return (
    <section className="rounded-xl border border-border bg-card shadow-xs">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-4 py-2 text-[12.5px]">
        <History className="size-3.5 text-muted-foreground" aria-hidden />
        {q.isError ? (
          <span className="text-destructive">Nie udało się pobrać historii automatycznych sprawdzeń.</span>
        ) : !q.isSuccess ? (
          <span className="text-muted-foreground">Ładowanie historii sprawdzeń…</span>
        ) : (
          <>
            <span className="text-muted-foreground">Ostatnie automatyczne sprawdzenie</span>
            <span className="font-medium tabular-nums text-foreground">{recheckSummary(data) ?? "—"}</span>
            <span className="text-muted-foreground">{hours}</span>
            {(data?.items ?? []).length ? (
              <Button type="button" variant="tertiary" size="sm" className="ml-auto h-7 px-0" onClick={() => setOpen((v) => !v)}>
                {open ? "Zwiń historię" : `Pokaż historię (${data?.items.length})`}
              </Button>
            ) : (
              <span className="ml-auto text-muted-foreground">Historia pusta — nic się nie zmieniało.</span>
            )}
          </>
        )}
      </div>
      {open && data ? (
        <div className="border-t border-border/60">
          <RecheckTable runs={data.items} limit={12} />
        </div>
      ) : null}
    </section>
  );
}

// ── Kolejka i szczegół ─────────────────────────────────────────────────────

export function QueueNote({ error, children }: { error?: boolean; children: ReactNode }) {
  return (
    <p
      className={cn(
        "rounded-xl border border-border bg-card px-4 py-6 text-[13px] shadow-xs",
        error ? "text-destructive" : "text-muted-foreground",
      )}
    >
      {children}
    </p>
  );
}

function QueueList({
  items,
  selectedId,
  onSelect,
}: {
  items: OrderMailDocument[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  return (
    <ul className="max-h-[calc(100dvh-15rem)] space-y-0.5 overflow-y-auto rounded-xl border border-border bg-card p-1.5 shadow-xs">
      {items.map((d) => {
        const points = d.outcome === "needs_review" || d.outcome === "unrecognized_client" ? checkPoints(d) : [];
        const first = points[0];
        const Icon = first ? POINT_ICON[first.kind] : null;
        const active = d.id === selectedId;
        return (
          <li key={d.id}>
            <button
              type="button"
              onClick={() => onSelect(d.id)}
              aria-current={active ? "true" : undefined}
              className={cn(
                "w-full rounded-lg px-2.5 py-2 text-left transition-colors",
                active ? "bg-primary/10" : "hover:bg-muted",
              )}
            >
              <span className="flex items-baseline justify-between gap-2">
                <span className="truncate text-[13px] font-semibold text-foreground">
                  {d.client_name ?? "Nierozpoznany klient"}
                </span>
                <span className="shrink-0 text-[11.5px] tabular-nums text-muted-foreground">{shortDay(d.received_at)}</span>
              </span>
              <span className="block truncate text-[12px] text-muted-foreground">
                {orderNumber(d) ?? "bez numeru"} · {plural(peopleCount(d), OSOBY)}
              </span>
              {first && Icon ? (
                <span className="mt-1 flex items-center gap-1.5 text-[12px] font-medium text-warning-muted-foreground">
                  <Icon className="size-3.5 shrink-0" aria-hidden />
                  {POINT_SHORT[first.kind]}
                  {points.length > 1 ? <span className="font-normal text-muted-foreground">+{points.length - 1}</span> : null}
                </span>
              ) : null}
              {d.applied_order_id ? (
                <span className="mt-1 flex items-center gap-1.5 text-[12px] text-success-muted-foreground">
                  <CircleCheck className="size-3.5 shrink-0" aria-hidden />
                  Zamówienie #{d.applied_order_id}
                </span>
              ) : null}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export function applyBlockedReason(doc: OrderMailDocument): string | null {
  if (!doc.can_apply) return "Zapis wymaga admina albo przypisanego Delivery Leada";
  if (!(doc.proposal?.rows?.length ?? 0)) return "Brak osób w planie — wprowadź zamówienie ręcznie";
  if (needsPersonDecision(doc)) return "Osobę rozstrzygnij w oknie zamówienia klienta";
  return null;
}

function DetailA({ doc }: { doc: OrderMailDocument }) {
  const points = checkPoints(doc);
  const ex = doc.extraction;
  const number = orderNumber(doc);
  const review = doc.outcome === "needs_review";
  const blocked = review ? applyBlockedReason(doc) : null;
  const recheck = recheckLine(doc);
  const canDismiss = doc.can_dismiss === true || doc.can_apply;
  return (
    <section className="flex min-w-0 flex-col rounded-xl border border-border bg-card shadow-xs">
      <header className="flex items-start justify-between gap-3 border-b border-border/60 px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold leading-5 text-foreground">
            {doc.client_name ?? "Nierozpoznany klient"}
            {number ? <span className="font-normal text-muted-foreground"> · zamówienie {number}</span> : null}
          </h2>
          <p className="mt-0.5 truncate text-[12.5px] text-muted-foreground" title={doc.subject ?? undefined}>
            Wpłynęło {formatDateTimePl(doc.received_at)} od {personFromEmail(doc.sender_email)}
            {doc.subject ? ` · „${doc.subject}”` : ""}
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!doc.has_file}
          title={doc.has_file ? (doc.attachment_name ?? undefined) : "Brak pliku PDF przy tym wpisie"}
        >
          <FileText className="size-3.5" aria-hidden />
          PDF
        </Button>
      </header>

      <div className="space-y-4 px-4 py-3">
        <div>
          <h3 className={SECTION_LABEL}>Co odczytano</h3>
          {/* Numer zamówienia stoi w nagłówku — tu klient (jak rozpoznany) i okres, po jednej linii. */}
          <dl className="mt-1.5 grid grid-cols-[120px_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-[13px] leading-5">
            <dt className="text-muted-foreground">Klient</dt>
            <dd className="min-w-0 truncate" title={identLabel(doc)}>
              <span className="font-medium text-foreground">{doc.client_name ?? "nie rozpoznano"}</span>
              <span className="text-muted-foreground"> · {identLabel(doc)}</span>
            </dd>
            <dt className="text-muted-foreground">Okres zamówienia</dt>
            <dd className="tabular-nums text-foreground">{ex ? period(ex.start_date, ex.end_date) : "—"}</dd>
          </dl>
          <div className="mt-2.5">
            <PlanTable doc={doc} />
          </div>
        </div>

        {points.length ? (
          <div>
            <h3 className={SECTION_LABEL}>Do sprawdzenia · {points.length}</h3>
            <div className="mt-2">
              <CheckList points={points} />
            </div>
            {recheck ? <p className="mt-2.5 text-[12px] text-muted-foreground">{recheck}</p> : null}
          </div>
        ) : null}

        {doc.applied_order_id ? (
          <p className="flex items-center gap-1.5 text-[13px] text-foreground">
            <Check className="size-3.5 text-success" aria-hidden />
            Zapisane jako zamówienie #{doc.applied_order_id}
            {doc.applied_at ? <span className="text-muted-foreground">· {formatDateTimePl(doc.applied_at)}</span> : null}
            {doc.client_id ? (
              <Link href={`/clients/${doc.client_id}?tab=zamowienia`} className="ml-1 font-medium text-primary hover:underline">
                Otwórz zamówienia klienta
              </Link>
            ) : null}
          </p>
        ) : null}
      </div>

      {review || ((doc.outcome === "unrecognized_client" || doc.outcome === "failed") && canDismiss) ? (
        <footer className="mt-auto flex items-center gap-2 border-t border-border/60 bg-muted/30 px-4 py-2.5">
          {review ? (
            <Button type="button" size="sm" disabled={blocked != null} title={blocked ?? undefined}>
              <Check className="size-3.5" aria-hidden />
              Zastosuj
            </Button>
          ) : null}
          {blocked ? <span className="text-[12px] text-muted-foreground">{blocked}</span> : null}
          <Button type="button" variant="quiet" size="sm" className="ml-auto" disabled={!canDismiss}>
            <X className="size-3.5" aria-hidden />
            Odrzuć
          </Button>
        </footer>
      ) : null}
    </section>
  );
}

export function OrderMailA() {
  const [outcome, setOutcome] = useState<OrderMailOutcome>("needs_review");
  const [selected, setSelected] = useState<number | null>(null);
  const counts = useMkOrderMailCounts();
  const queue = useMkOrderMailQueue(outcome);
  const sync = useMkOrderMailSync();
  const items = queue.data?.items ?? [];
  const doc = items.find((d) => d.id === selected) ?? items[0] ?? null;
  const tab = OUTCOME_TABS.find((t) => t.outcome === outcome);

  return (
    <div className="space-y-3">
      <OrderMailHead status={sync.data} failed={sync.isError} />
      <TabsBar
        items={outcomeTabItems(counts)}
        value={outcome}
        onChange={(o) => {
          setOutcome(o);
          setSelected(null);
        }}
      />
      {queue.isError ? (
        <QueueNote error>Nie udało się pobrać kolejki — odśwież stronę.</QueueNote>
      ) : !queue.isSuccess ? (
        <QueueNote>Ładowanie kolejki…</QueueNote>
      ) : items.length === 0 ? (
        <QueueNote>{tab?.empty}</QueueNote>
      ) : (
        <div className="grid grid-cols-[264px_minmax(0,1fr)] items-start gap-4">
          <QueueList items={items} selectedId={doc?.id ?? null} onSelect={setSelected} />
          {doc ? <DetailA key={doc.id} doc={doc} /> : null}
        </div>
      )}
      {(queue.data?.total ?? 0) > items.length ? (
        <p className="text-[12px] text-muted-foreground">
          Pokazano {items.length} najnowszych z {queue.data?.total}.
        </p>
      ) : null}
      <RecheckFooter />
    </div>
  );
}
