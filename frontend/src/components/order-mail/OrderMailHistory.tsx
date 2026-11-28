"use client";

import { Fragment, useState } from "react";
import Link from "next/link";
import { History } from "lucide-react";
import { Button } from "@/components/ui/button";
import { QueryStateNotice } from "@/components/ds";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { cn } from "@/lib/utils";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import type { OrderMailRecheckEntry, OrderMailRecheckRun, OrderMailRecheckWindow } from "@/lib/api/orderMail";
import { formatDateTimePl } from "@/lib/date-pl";
import { plural, reasonLabel } from "@/lib/order-mail-sync";
import { historyRows, isQuiet, RECHECK_CATEGORY_LABEL, recheckEntryLabel } from "@/lib/order-mail-history";

// `forbidden` osobno od `error`: odmowa sekcji to brak dostępu, nie awaria do ponowienia.
export type OrderMailViewState = "loading" | "error" | "forbidden" | "ready";

export interface RecheckHistoryProps {
  runs: OrderMailRecheckRun[];
  state: OrderMailViewState;
  /** Liczby policzone z widocznych wpisów (Delivery Lead widzi swój portfel). */
  scoped: boolean;
  /**
   * Kiedy weryfikacja ostatnio cokolwiek sprawdziła. Wiersz w historii powstaje
   * tylko przy zmianie, więc pusta historia pod aktualnym znacznikiem znaczy
   * „nic nie wymagało zmiany”, a nie „to nie działa”. Brak wartości (serwer
   * sprzed wdrożenia) → zdanie się nie renderuje.
   */
  lastCheckedAt?: string | null;
  /** Ile sprawdzeń z rzędu nic nie zmieniło — „bez zmian”. */
  unchangedRuns?: number;
  window?: OrderMailRecheckWindow;
  onRetry: () => void;
}

/**
 * Kadencja słowami. Wyrównane godziny znaczą „okno wyłączone”; serwer sprzed
 * wdrożenia okna nie przysyła pola — i wtedy faktycznie chodzi całą dobę.
 */
function scheduleLabel(w: OrderMailRecheckWindow | undefined): string {
  if (!w || !w.enabled) return "co godzinę, całą dobę";
  const hh = (h: number) => `${String(h).padStart(2, "0")}:00`;
  return `co godzinę w godzinach ${hh(w.start_hour)}–${hh(w.end_hour)}`;
}

/** Początek zdania o kadencji — „całą dobę” potrzebuje przecinka przed dalszym ciągiem. */
function scheduleSentence(w: OrderMailRecheckWindow | undefined): string {
  const label = scheduleLabel(w);
  return `${label.charAt(0).toUpperCase()}${label.slice(1)}${!w || !w.enabled ? "," : ""}`;
}

const ENTRY_STATUS: Record<string, { tone: StatusDotTone; label: string }> = {
  applied: { tone: "success", label: "Zapisane" },
  // Dokument powtarzał zapisane zamówienie — zamknięty bez zmian (28.11.2026).
  closed: { tone: "neutral", label: "Zamknięte bez zmian" },
  error: { tone: "danger", label: "Błąd" },
};

function EntryList({ entries }: { entries: OrderMailRecheckEntry[] }) {
  return (
    <ul className="space-y-2" data-testid="recheck-entries">
      {entries.map((e) => {
        const status = ENTRY_STATUS[e.outcome] ?? { tone: "warning" as const, label: "Wstrzymane" };
        return (
          <li key={e.document_id} className="text-[13px]">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <StatusDot tone={status.tone}>{status.label}</StatusDot>
              <Link
                href={`/contracts?view=order-mail&doc=${e.document_id}`}
                className="font-medium text-primary underline-offset-2 hover:underline"
              >
                {recheckEntryLabel(e)}
              </Link>
              {e.client_name ? <span className="text-muted-foreground">{e.client_name}</span> : null}
              {e.category ? (
                <span className="text-xs text-muted-foreground">{RECHECK_CATEGORY_LABEL[e.category] ?? e.category}</span>
              ) : null}
            </div>
            {e.reasons.length > 0 ? (
              <ul className="mt-0.5 list-disc pl-5 text-xs text-muted-foreground">
                {e.reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

const SHOWN_AT_ONCE = 12;

/**
 * Tabela biegów: co zmienił każdy bieg, a wiersz rozwija się do konkretnych
 * dokumentów z powodem i linkiem do wpisu — sama liczba „3 wstrzymane” nie
 * mówi, czym się zająć.
 */
function RecheckTable({ runs, scoped, window: w }: { runs: OrderMailRecheckRun[]; scoped: boolean; window?: OrderMailRecheckWindow }) {
  const [openRun, setOpenRun] = useState<number | null>(null);
  const [showQuiet, setShowQuiet] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const { rows, quiet } = historyRows(runs);
  const visible = showQuiet ? rows : rows.filter((r) => !isQuiet(r));
  const shown = showAll ? visible : visible.slice(0, SHOWN_AT_ONCE);
  return (
    <div className="border-t border-border/60">
      <p className="max-w-4xl px-4 pt-2 text-xs text-muted-foreground">
        {scheduleSentence(w)} system sam próbuje dokończyć wstrzymane zamówienia. Wiersz powstaje tylko wtedy, gdy
        sprawdzenie coś zmieniło. Zamówienie czekające na podpis umowy nowego kontraktora czeka bez limitu czasu
        i nie powiadamia Delivery Leada.
        {scoped ? " Liczby dotyczą Twojego portfela klientów." : ""}
      </p>
      <div className="mt-1 overflow-x-auto">
        <table className="w-full min-w-[40rem] text-[13px]">
          <thead>
            <tr className="border-b border-border">
              <th className={cn(CALM_HEAD, "w-[150px] py-2 pl-4 pr-3 text-left")}>Kiedy</th>
              <th className={cn(CALM_HEAD, "w-[96px] px-3 py-2 text-right")}>Sprawdzono</th>
              <th className={cn(CALM_HEAD, "w-[84px] px-3 py-2 text-right")}>Zapisano</th>
              <th className={cn(CALM_HEAD, "w-[96px] px-3 py-2 text-right")}>Wstrzymano</th>
              <th className={cn(CALM_HEAD, "py-2 pl-3 pr-3 text-left")}>Co się zmieniło</th>
              <th className={cn(CALM_HEAD, "w-[88px] py-2 pl-3 pr-4 text-left")}>Wpisy</th>
            </tr>
          </thead>
          <tbody>
            {shown.map(({ run, changes, oldest }) => (
              <Fragment key={run.id}>
                <tr className={cn(CALM_ROW, "align-top")} data-testid="recheck-run">
                  <td className="whitespace-nowrap py-2 pl-4 pr-3 tabular-nums">
                    {formatDateTimePl(run.started_at)}
                    <span className={CALM_SUBLINE}>{reasonLabel(run.trigger)}</span>
                  </td>
                  <td className={cn(CALM_AMOUNT, "px-3 py-2 text-muted-foreground")}>{run.checked}</td>
                  <td className={cn(CALM_AMOUNT, "px-3 py-2", run.applied ? "font-semibold text-foreground" : "text-muted-foreground")}>
                    {run.applied}
                  </td>
                  <td className={cn(CALM_AMOUNT, "px-3 py-2 text-muted-foreground")}>{run.held}</td>
                  <td className="py-2 pl-3 pr-3">
                    {changes.length ? (
                      <span className="line-clamp-2" title={changes.join("\n")}>
                        {changes.join(" · ")}
                      </span>
                    ) : oldest ? (
                      <span className="text-muted-foreground">najstarszy wiersz w historii (30 dni)</span>
                    ) : run.entries.length ? (
                      <span className="text-muted-foreground">zmienił się tylko stan powiadomień</span>
                    ) : (
                      <span className="text-muted-foreground">nic do sprawdzenia</span>
                    )}
                  </td>
                  <td className="py-2 pl-3 pr-4">
                    {run.entries.length ? (
                      <button
                        type="button"
                        className="whitespace-nowrap text-primary underline-offset-2 hover:underline"
                        aria-expanded={openRun === run.id}
                        onClick={() => setOpenRun(openRun === run.id ? null : run.id)}
                      >
                        {openRun === run.id ? "Zwiń" : `Pokaż (${run.entries.length})`}
                      </button>
                    ) : (
                      <span className="text-muted-foreground/50">—</span>
                    )}
                  </td>
                </tr>
                {openRun === run.id ? (
                  <tr className={CALM_ROW}>
                    <td colSpan={6} className="bg-muted/40 px-4 py-3">
                      <EntryList entries={run.entries} />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {visible.length > SHOWN_AT_ONCE || quiet > 0 ? (
        <div className="flex flex-wrap gap-x-5 border-t border-border/60 px-4 py-1.5">
          {visible.length > SHOWN_AT_ONCE ? (
            <Button type="button" variant="tertiary" size="sm" className="px-0" onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Pokaż tylko najnowsze" : `Pokaż starsze (${visible.length - SHOWN_AT_ONCE})`}
            </Button>
          ) : null}
          {quiet > 0 ? (
            <Button type="button" variant="tertiary" size="sm" className="px-0" onClick={() => setShowQuiet((v) => !v)}>
              {showQuiet
                ? "Ukryj wiersze, w których zmienił się tylko stan powiadomień"
                : `Pokaż też ${quiet} ${plural(quiet, "wiersz", "wiersze", "wierszy")}, w których zmienił się tylko stan powiadomień`}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/**
 * „Historia automatycznej weryfikacji” — zwinięta do jednej linii na dole
 * kolejki (przebudowa 20.11.2026, wariant A): kadencja, „Sprawdzone ostatnio”
 * i przycisk rozwijający tabelę biegów.
 *
 * Gałęzie w tej samej kolejności co reszta ekranu: awaria NIE MOŻE renderować
 * się jako pustka, a pusty stan wisi na `ready` (po udanym odczycie). Historia
 * ma własne zapytanie i stoi także przy padniętej kolejce — to ona mówi, czy
 * system w ogóle próbuje dokończyć wstrzymane wpisy.
 */
export function RecheckHistoryPanel(p: RecheckHistoryProps) {
  const [open, setOpen] = useState(false);
  const ready = p.state === "ready";
  return (
    <section
      className="rounded-xl border border-border bg-card shadow-xs"
      data-testid="recheck-history"
      data-help="contracts.order_mail.history"
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-4 py-2 text-[12.5px]">
        <History className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
        <h2 className="text-[13px] font-medium leading-5 text-foreground">Historia automatycznej weryfikacji</h2>
        <span className="text-muted-foreground">· {scheduleLabel(p.window)}</span>
        {p.lastCheckedAt ? (
          <span className="text-muted-foreground" data-testid="recheck-last-checked" role="status">
            · Sprawdzone ostatnio:{" "}
            <span className="font-medium tabular-nums text-foreground">{formatDateTimePl(p.lastCheckedAt)}</span>
            {p.unchangedRuns ? " — bez zmian" : ""}
          </span>
        ) : null}
        <span className="ml-auto">
          {ready && p.runs.length > 0 ? (
            <Button
              type="button"
              variant="tertiary"
              size="sm"
              className="h-7 px-0"
              aria-expanded={open}
              onClick={() => setOpen((v) => !v)}
            >
              {open ? "Zwiń historię" : `Pokaż historię (${p.runs.length})`}
            </Button>
          ) : ready ? (
            <span className="text-muted-foreground">
              Brak zmian do pokazania — tu trafiają tylko sprawdzenia, które coś zmieniły.
            </span>
          ) : p.state === "loading" ? (
            <span className="text-muted-foreground">Ładowanie historii…</span>
          ) : null}
        </span>
      </div>
      {p.state === "error" || p.state === "forbidden" ? (
        <QueryStateNotice
          state={p.state === "forbidden" ? "forbidden" : "error"}
          className="mx-4 mb-3 py-6"
          description="Nie udało się pobrać historii ponownej weryfikacji."
          onRetry={p.state === "error" ? p.onRetry : undefined}
        />
      ) : null}
      {open && ready && p.runs.length > 0 ? <RecheckTable runs={p.runs} scoped={p.scoped} window={p.window} /> : null}
    </section>
  );
}
