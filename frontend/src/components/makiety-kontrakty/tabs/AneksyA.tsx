"use client";
// A · Aneksy — „Oś zmian”. Dziś: pięć kolorowych przycisków, akapit objaśnień
// nad i pod tabelą, etykiety łamane w trzy linie, „Dokument: brak” i „Źródło:
// Ręcznie” w każdym wierszu, a trzy identyczne wpisy bez słowa komentarza.
// Tu: karta „Obowiązuje teraz” (stan z kontraktu, skąd wzięła się stawka)
// z jedną akcją „Dodaj aneks ▾”, pod nią oś czasu po dacie wejścia w życie,
// zmiana w jednej linii, pochodzenie drobnym drukiem, uzasadnienie jako cytat,
// powtórzone wpisy zwinięte z cichym ostrzeżeniem.
//
// Pomocnicze funkcje (etykiety, linia zmiany, wykrywanie powtórzeń, odczyt
// aneksów z generatora) są eksportowane — korzysta z nich wariant B.
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, Paperclip } from "lucide-react";
import { contractDetailLabel, contractDetailValue } from "@/components/contracts/contract-timeline-labels";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import api from "@/lib/api";
import type { AnnexChange, AnnexState } from "@/lib/api/b2bDocuments";
import { annexChangeText, annexTitle } from "@/lib/b2b-documents";
import { CALM_HEAD } from "@/lib/calm-table";
import { currencySymbol, rateUnitSuffix } from "@/lib/money";
import { cn } from "@/lib/utils";
import {
  useMkAmendments,
  useMkContract,
  type MkAmendment,
  type MkContract,
  type MkRateStep,
} from "../shared/data";
import { CONTRACT_STATUS_LABEL, fmtDate, fmtNum, personFromEmail, plural, relDays, today } from "../shared/format";
import { warsawDay } from "./DokumentyA";
import type { TabProps } from "./types";

// ── Dane wspólne dla A i B ────────────────────────────────────────────────

/** Aneks z Generatora aneksów bez wpisu w kontrakcie (czeka na podpis, anulowany). */
export interface MkAnnexDocument {
  document_id: number;
  document_type: string;
  type_label: string;
  state: AnnexState;
  effective_date: string | null;
  change: AnnexChange | null;
  cancelled_reason: string | null;
  created_at: string | null;
  created_by_name: string | null;
}

export function useMkAnnexDocuments(id: number) {
  return useQuery<MkAnnexDocument[]>({
    queryKey: ["mk-annex-documents", id],
    queryFn: () => api.get<MkAnnexDocument[]>(`/api/contracts/${id}/annex-documents`).then((r) => r.data),
    enabled: Number.isFinite(id),
  });
}

/** Umowa B2B bez zakończenia jest bezterminowa — backend odrzuca przedłużenie (`b2bExtensionLocked`). */
export function extensionLocked(c: MkContract): boolean {
  return (c.contract_type ?? "b2b") === "b2b" && !c.terminated_at && !c.termination_reason;
}

export const EXTENSION_LOCKED_HINT = "Umowa B2B jest bezterminowa — przedłuż zamówienie klienta.";

const TYPE_LABEL: Record<string, string> = {
  extension: "Przedłużenie",
  rate_change: "Zmiana stawki",
  scope_change: "Zmiana zakresu",
  early_termination: "Wcześniejsze zakończenie",
  start_date_change: "Zmiana daty startu",
  party_data_change: "Dane firmy",
  subcontractor_consent: "Osoba skierowana",
  mandate_change: "Aneks do zlecenia",
  custom_change: "Inna zmiana",
};

/** „Zmiana stawek” / „Zmiana stawki kandydata” / „Przedłużenie”; aneks z własną nazwą — ta nazwa. */
export function amendmentTitle(a: MkAmendment, short = false): string {
  const nv = a.new_values ?? {};
  const title = nv.annex_title;
  if (a.amendment_type === "custom_change" && typeof title === "string" && title.trim()) return title.trim();
  if (a.amendment_type === "rate_change") {
    const client = "rate_client" in nv;
    const cand = "rate_candidate" in nv;
    if (client && cand) return "Zmiana stawek";
    if (short) return "Zmiana stawki";
    if (client) return "Zmiana stawki klienta";
    if (cand) return "Zmiana stawki kandydata";
  }
  return TYPE_LABEL[a.amendment_type] ?? "Aneks";
}

const HIDDEN_KEYS = new Set(["annex_title", "withdrawn_amendment_id"]);
const RATE_WHO: Record<string, string> = { rate_client: "klient", rate_candidate: "kandydat", framework_rate: "stawka ramowa" };

const asNumber = (v: unknown): number | null => {
  const n = typeof v === "number" ? v : typeof v === "string" && v.trim() ? Number(v) : NaN;
  return Number.isFinite(n) ? n : null;
};

/** „175,00” albo w wersji zwartej „175” (ułamki zostają: „34,625”). */
export function rateNum(v: number, compact = false): string {
  return compact
    ? v.toLocaleString("pl-PL", { minimumFractionDigits: 0, maximumFractionDigits: 3 })
    : fmtNum(v, Math.round(v * 1000) % 10 === 0 ? 2 : 3);
}

export function rateUnit(c: MkContract | undefined): string {
  return `${currencySymbol(c?.currency)}${rateUnitSuffix(c?.rate_unit ?? "hourly")}`;
}

/**
 * Zmiana w jednej linii: „klient 175,00 → 163,00 zł/h · kandydat 135,00 → 125,00 zł/h”.
 * `compact` — liczby bez zbędnych groszy i bez jednostki (jednostka w nagłówku kolumny).
 */
export function changeLine(a: MkAmendment, unit: string, compact = false): string {
  const oldV = a.old_values ?? {};
  const newV = a.new_values ?? {};
  const u = compact ? "" : ` ${unit}`;
  const parts: string[] = [];
  for (const [key, next] of Object.entries(newV)) {
    if (HIDDEN_KEYS.has(key)) continue;
    const prev = oldV[key];
    if (RATE_WHO[key]) {
      const n = asNumber(next);
      const p = asNumber(prev);
      if (n == null) continue;
      if (p == null) parts.push(`${RATE_WHO[key]} ${rateNum(n, compact)}${u}`);
      else if (p === n) parts.push(`${RATE_WHO[key]} ${rateNum(n, compact)}${u} bez zmiany kwoty`);
      else parts.push(`${RATE_WHO[key]} ${rateNum(p, compact)} → ${rateNum(n, compact)}${u}`);
      continue;
    }
    if (key === "status") {
      if (prev === next) continue;
      const label = (v: unknown) => (CONTRACT_STATUS_LABEL[String(v)] ?? String(v ?? "—")).toLocaleLowerCase("pl");
      parts.push(`status ${label(prev)} → ${label(next)}`);
      continue;
    }
    if (key === "end_date") {
      const after = next == null ? "bezterminowo" : fmtDate(String(next));
      const shorter = typeof prev === "string" && typeof next === "string" && next < prev;
      const label = compact ? "koniec" : "koniec projektu";
      parts.push(`${label} ${prev ? `${fmtDate(String(prev))} → ` : ""}${after}${shorter ? (compact ? " (wcześniej)" : " (wcześniej niż było)") : ""}`);
      continue;
    }
    const label = contractDetailLabel(key).toLocaleLowerCase("pl");
    const before = contractDetailValue(key, prev);
    const after = contractDetailValue(key, next);
    parts.push(before !== "—" && before !== after ? `${label} ${before} → ${after}` : `${label} ${after}`);
  }
  return parts.join(" · ");
}

export function authorOf(a: MkAmendment): string {
  return a.created_by_name || personFromEmail(a.created_by_email);
}

const WARSAW_TIME = new Intl.DateTimeFormat("pl-PL", { timeZone: "Europe/Warsaw", hour: "2-digit", minute: "2-digit" });

/** „29.06.2026, 15:11” w kalendarzu firmy. */
export function savedAt(iso: string): string {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? fmtDate(iso) : `${fmtDate(warsawDay(iso))}, ${WARSAW_TIME.format(t)}`;
}

const stable = (v: unknown): string =>
  v && typeof v === "object" && !Array.isArray(v)
    ? `{${Object.keys(v as Record<string, unknown>)
        .sort()
        .map((k) => `${k}:${stable((v as Record<string, unknown>)[k])}`)
        .join(",")}}`
    : JSON.stringify(v ?? null);

/** Ten sam rodzaj + dzień wejścia w życie + nowe wartości = ten sam aneks zapisany drugi raz. */
export function dupKey(a: MkAmendment): string {
  return `${a.amendment_type}|${a.effective_date ?? ""}|${stable(a.new_values)}`;
}

export interface AmendmentGroup {
  /** Pierwszy zapis (najstarszy) — reszta to powtórzenia. */
  first: MkAmendment;
  /** Wszystkie zapisy od najnowszego. */
  all: MkAmendment[];
  reason: string | null;
}

/** Wpisy zgrupowane po `dupKey`, od najnowszego dnia wejścia w życie, w dniu — od najnowszego zapisu. */
export function groupAmendments(list: readonly MkAmendment[]): AmendmentGroup[] {
  const map = new Map<string, MkAmendment[]>();
  for (const a of list) map.set(dupKey(a), [...(map.get(dupKey(a)) ?? []), a]);
  return [...map.values()]
    .map((all) => {
      const sorted = [...all].sort((x, y) => y.created_at.localeCompare(x.created_at));
      const first = sorted[sorted.length - 1];
      return { first, all: sorted, reason: sorted.map((x) => x.reason).find((r) => r && r.trim()) ?? null };
    })
    .sort(
      (x, y) =>
        (y.first.effective_date ?? "").localeCompare(x.first.effective_date ?? "") ||
        y.first.created_at.localeCompare(x.first.created_at),
    );
}

// ── Wariant A ─────────────────────────────────────────────────────────────

const ADD_ITEMS = ["Zmiana stawki", "Zmiana zakresu", "Przedłużenie", "Zakończenie wcześniej", "Wygeneruj dokument aneksu"];

function AddAnnexMenu({ locked }: { locked: boolean }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="outline" size="sm" title={`Dodaj aneks: ${ADD_ITEMS.join(", ")}`}>
          Dodaj aneks
          <ChevronDown className="size-3.5" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-72">
        <DropdownMenuItem>Zmiana stawki</DropdownMenuItem>
        <DropdownMenuItem>Zmiana zakresu</DropdownMenuItem>
        <DropdownMenuItem disabled={locked} className="flex-col items-start gap-0">
          Przedłużenie
          {locked ? <span className="text-[11.5px] text-muted-foreground">{EXTENSION_LOCKED_HINT}</span> : null}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem className="text-muted-foreground focus:bg-destructive/10 focus:text-destructive">
          Zakończenie wcześniej…
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem className="flex-col items-start gap-0">
          Wygeneruj dokument aneksu
          <span className="text-[11.5px] text-muted-foreground">Generator aneksów — zmiana po podpisie</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Krok harmonogramu stawki obowiązujący dziś (ostatni z datą ≤ dziś). */
function stepToday(steps: MkRateStep[] | undefined, rate: number | null): MkRateStep | null {
  const t = today();
  const live = (steps ?? [])
    .filter((s) => !s.superseded && (s.effective_from ?? "") <= t)
    .sort((a, b) => (a.effective_from ?? "").localeCompare(b.effective_from ?? ""));
  const last = live[live.length - 1];
  return last && rate != null && Math.abs(last.rate - rate) < 0.001 ? last : null;
}

function NowCard({ c, locked }: { c: MkContract; locked: boolean }) {
  const unit = rateUnit(c);
  const client = stepToday(c.client_rate_schedule, c.rate_client);
  const cand = stepToday(c.candidate_rate_schedule, c.rate_candidate);
  const sameDay = client?.effective_from && client.effective_from === cand?.effective_from ? client.effective_from : null;
  const orderEnd = c.latest_order_end_date ?? c.client_order_end_date;
  const rate = (who: string, v: number | null, step: MkRateStep | null) => (
    <span>
      {who}{" "}
      <span className="font-semibold tabular-nums text-foreground">
        {v == null ? "—" : `${rateNum(v)} ${unit}`}
      </span>
      {!sameDay && step?.effective_from ? (
        <span className="text-muted-foreground"> od {fmtDate(step.effective_from)}</span>
      ) : null}
    </span>
  );
  const fromOrder = [
    client?.source_order_id ? "stawka klienta" : null,
    cand?.source_order_id ? "stawka kandydata" : null,
  ].filter(Boolean);
  const facts = [
    c.end_date ? `umowa do ${fmtDate(c.end_date)}` : c.contract_type === "b2b" ? "umowa B2B bezterminowa" : null,
    fromOrder.length > 0 ? `${fromOrder.join(" i ")} z zamówienia klienta, nie z aneksu` : null,
  ].filter(Boolean);

  return (
    <section className="rounded-xl border border-border bg-card px-4 py-3 shadow-xs">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <h2 className={CALM_HEAD}>Obowiązuje teraz</h2>
          <p className="text-[14.5px] leading-6 text-foreground">
            {sameDay ? <span className="text-muted-foreground">Od {fmtDate(sameDay)}: </span> : null}
            {rate("klient", c.rate_client, client)}
            <span className="text-muted-foreground"> · </span>
            {rate("kandydat", c.rate_candidate, cand)}
            {orderEnd ? (
              <>
                <span className="text-muted-foreground"> · </span>
                zamówienie do <span className="font-semibold tabular-nums">{fmtDate(orderEnd)}</span>
              </>
            ) : null}
          </p>
          {facts.length > 0 ? <p className="text-[12.5px] text-muted-foreground">{facts.join(" · ")}</p> : null}
        </div>
        <AddAnnexMenu locked={locked} />
      </div>
    </section>
  );
}

function Meta({ a }: { a: MkAmendment }) {
  const generator = a.source === "generator";
  const doc = a.document as { id: number; filename: string; is_signed_scan: boolean } | null | undefined;
  return (
    <p className="flex flex-wrap items-center gap-x-1.5 text-[12px] leading-5 text-muted-foreground">
      <span>{generator ? "z Generatora aneksów" : "ręcznie"}</span>
      <span aria-hidden>·</span>
      {doc ? (
        <button type="button" className="inline-flex min-w-0 items-center gap-1 text-primary hover:underline" title={doc.filename}>
          <Paperclip className="size-3 shrink-0" aria-hidden />
          <span className="max-w-[360px] truncate">{doc.filename}</span>
        </button>
      ) : (
        <span>bez dokumentu</span>
      )}
      {generator && doc && !doc.is_signed_scan ? (
        <>
          <span aria-hidden>·</span>
          <span>bez podpisów</span>
          <button type="button" className="font-medium text-primary hover:underline">
            Dołącz skan
          </button>
        </>
      ) : null}
      <span aria-hidden>·</span>
      <span>
        {authorOf(a)}, {fmtDate(warsawDay(a.created_at))}
      </span>
    </p>
  );
}

function GroupEntry({ g, unit }: { g: AmendmentGroup; unit: string }) {
  const [open, setOpen] = useState(false);
  const a = g.first;
  const repeated = g.all.length > 1;
  const muted = a.withdrawn || a.state === "cancelled";
  const change = changeLine(a, unit);
  return (
    <div className={cn("space-y-1", muted && "opacity-60")}>
      <p className="flex flex-wrap items-baseline gap-x-2 text-[13.5px] font-semibold leading-5 text-foreground">
        {amendmentTitle(a)}
        {a.withdrawn ? <span className="text-[12px] font-normal text-muted-foreground">wycofane</span> : null}
        {a.state === "signed_pending" ? (
          <span className="text-[12px] font-normal text-info">podpisany · wejdzie w życie {relDays(a.effective_date)}</span>
        ) : null}
      </p>
      {change ? <p className="text-[13px] leading-5 tabular-nums text-foreground">{change}</p> : null}
      <Meta a={a} />
      {g.reason ? (
        <blockquote className="border-l-2 border-border pl-3 text-[12.5px] leading-5 text-muted-foreground">
          „{g.reason}”
        </blockquote>
      ) : null}
      {a.withdrawable ? (
        <Button type="button" variant="quiet" size="sm" className="-ml-3 h-7">
          Wycofaj wypowiedzenie
        </Button>
      ) : null}
      {repeated ? (
        <div className="text-[12px] leading-5 text-muted-foreground">
          <p className="flex flex-wrap items-center gap-x-1.5">
            <AlertTriangle className="size-3.5 shrink-0 text-warning" aria-hidden />
            zapisano {g.all.length} razy ({g.all.map((x) => fmtDate(warsawDay(x.created_at)).slice(0, 5)).join(", ")}) — możliwy
            duplikat
            <span aria-hidden>·</span>
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
              className="font-medium text-primary hover:underline"
            >
              {open ? "Ukryj wpisy" : "Pokaż wpisy"}
            </button>
          </p>
          {open ? (
            <ul className="mt-1 space-y-0.5 border-l border-border pl-3">
              {g.all.map((x) => (
                <li key={x.id} className="tabular-nums">
                  {savedAt(x.created_at)} · {authorOf(x)} · {x.reason ? "z uzasadnieniem" : "bez uzasadnienia"}
                  {x.id === a.id ? " · pierwszy zapis" : ""}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function PendingEntry({ d }: { d: MkAnnexDocument }) {
  const change = annexChangeText(d.change);
  return (
    <div className={cn("space-y-1", d.state === "cancelled" && "opacity-60")}>
      <p className="flex flex-wrap items-baseline gap-x-2 text-[13.5px] font-semibold leading-5 text-foreground">
        {annexTitle(d.document_type)}
        <span className={cn("text-[12px] font-normal", d.state === "waiting" ? "text-warning" : "text-muted-foreground")}>
          {d.state === "waiting" ? "czeka na podpis" : d.state === "cancelled" ? "anulowany" : "podpisany"}
        </span>
      </p>
      {change ? (
        <p className="text-[13px] leading-5 tabular-nums text-foreground">
          {change.before ? `${change.before} → ` : ""}
          {change.after}
        </p>
      ) : null}
      <p className="text-[12px] leading-5 text-muted-foreground">
        z Generatora aneksów{d.state === "waiting" ? " · zmieni kontrakt po oznaczeniu jako podpisany" : ""}
        {d.cancelled_reason ? ` · ${d.cancelled_reason}` : ""}
        {d.created_by_name ? ` · ${d.created_by_name}` : ""}
        {d.created_at ? `, ${fmtDate(warsawDay(d.created_at))}` : ""}
      </p>
    </div>
  );
}

interface DayNode {
  date: string | null;
  groups: AmendmentGroup[];
  pending: MkAnnexDocument[];
}

export function AneksyA({ contractId }: TabProps) {
  const c = useMkContract(contractId).data;
  const amendQ = useMkAmendments(contractId);
  const annexQ = useMkAnnexDocuments(contractId);

  const groups = useMemo(() => groupAmendments(amendQ.data ?? []), [amendQ.data]);
  const nodes = useMemo(() => {
    const byDay = new Map<string, DayNode>();
    const node = (date: string | null) => {
      const k = date ?? "";
      const n = byDay.get(k) ?? { date, groups: [], pending: [] };
      byDay.set(k, n);
      return n;
    };
    for (const g of groups) node(g.first.effective_date).groups.push(g);
    for (const d of annexQ.data ?? []) node(d.effective_date).pending.push(d);
    return [...byDay.values()].sort((x, y) => (y.date ?? "9999").localeCompare(x.date ?? "9999"));
  }, [groups, annexQ.data]);

  if (!c) return null;
  const unit = rateUnit(c);
  const locked = extensionLocked(c);
  const t = today();
  const currentDay = nodes.find((n) => n.date && n.date <= t)?.date ?? null;
  const records = amendQ.data?.length ?? 0;
  const repeats = records - groups.length;

  return (
    <div className="space-y-4">
      <NowCard c={c} locked={locked} />

      {amendQ.isLoading ? (
        <p className="text-sm text-muted-foreground">Ładowanie aneksów…</p>
      ) : amendQ.isError ? (
        <QueryStateNotice state="error" description="Nie udało się wczytać aneksów kontraktu." onRetry={() => void amendQ.refetch()} />
      ) : amendQ.isSuccess && annexQ.isSuccess && nodes.length === 0 ? (
        <p className="rounded-xl border border-border bg-card px-4 py-5 text-[13px] text-muted-foreground shadow-xs">
          Bez aneksów — stawki i okres są takie jak przy starcie. Zmianę zapiszesz przyciskiem „Dodaj aneks”.
        </p>
      ) : (
        <section className="rounded-xl border border-border bg-card px-4 pb-4 pt-3 shadow-xs">
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <h2 className="text-[13.5px] font-semibold text-foreground">Zmiany według daty wejścia w życie</h2>
            <span className="text-[12px] text-muted-foreground">
              {plural(groups.length, ["zmiana", "zmiany", "zmian"])}
              {repeats > 0 ? ` · ${plural(repeats, ["powtórzony wpis", "powtórzone wpisy", "powtórzonych wpisów"])}` : ""}
            </span>
          </div>
          {annexQ.isError ? (
            <p role="alert" className="mb-3 rounded-lg bg-destructive/10 px-3 py-2 text-[12.5px] text-destructive">
              Nie udało się wczytać aneksów czekających na podpis — oś pokazuje tylko zmiany już zapisane w kontrakcie.
            </p>
          ) : null}
          <ol>
            {nodes.map((n, i) => {
              const future = n.date != null && n.date > t;
              const current = n.date === currentDay;
              const last = i === nodes.length - 1;
              return (
                <li key={n.date ?? "bez-daty"} className="flex gap-3">
                  <div className="w-[92px] shrink-0 pt-px text-right">
                    <p className={cn("text-[13px] font-semibold tabular-nums", current ? "text-foreground" : "text-muted-foreground")}>
                      {n.date ? fmtDate(n.date) : "bez daty"}
                    </p>
                    {future ? <p className="text-[11.5px] text-info">{relDays(n.date)}</p> : null}
                    {current ? <p className="text-[11.5px] text-muted-foreground">obowiązuje</p> : null}
                  </div>
                  <div className="relative flex w-3 shrink-0 justify-center">
                    <span
                      aria-hidden
                      className={cn(
                        "relative z-10 mt-1 size-2.5 rounded-full border-2 bg-card",
                        current ? "border-primary" : future ? "border-info" : "border-muted-foreground/40",
                      )}
                    />
                    {!last ? <span aria-hidden className="absolute bottom-0 top-4 w-px bg-border" /> : null}
                  </div>
                  <div className={cn("min-w-0 flex-1 space-y-3", !last && "pb-5")}>
                    {n.pending
                      .filter((d) => d.state === "waiting")
                      .map((d) => (
                        <PendingEntry key={`d-${d.document_id}`} d={d} />
                      ))}
                    {n.groups.map((g) => (
                      <GroupEntry key={g.first.id} g={g} unit={unit} />
                    ))}
                    {n.pending
                      .filter((d) => d.state !== "waiting")
                      .map((d) => (
                        <PendingEntry key={`d-${d.document_id}`} d={d} />
                      ))}
                  </div>
                </li>
              );
            })}
          </ol>
        </section>
      )}

      <p className="text-[12px] text-muted-foreground">
        Aneks z generatora zmienia kontrakt dopiero po podpisie; aneks dodany tutaj działa od razu.
      </p>
    </div>
  );
}
