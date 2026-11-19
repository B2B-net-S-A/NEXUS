"use client";
// B · Aneksy — „Zwarta tabela”. Zamiast pięciu kolorowych przycisków jeden
// rząd neutralnych (`outline sm`), „Zakończ wcześniej” cicho na końcu,
// „Przedłuż” wyłączony z powodem w podpowiedzi zamiast akapitu nad tabelą.
// Tabela: Od · Rodzaj · Zmiana (jedna linia, jednostka w nagłówku) ·
// Dokument (plik albo cichy „Dodaj”) · Kto. Powtórzone wpisy zostają na
// liście (to rejestr), ale wyszarzone z dopiskiem „powtórzony wpis”.
// Etykiety, linia zmiany i grupowanie powtórzeń: `AneksyA.tsx`.
import { Fragment } from "react";
import { Paperclip } from "lucide-react";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { annexChangeText, annexTitle } from "@/lib/b2b-documents";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE, CALM_UNIT } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { useMkAmendments, useMkContract, type MkAmendment } from "../shared/data";
import { fmtDate } from "../shared/format";
import {
  amendmentTitle,
  authorOf,
  changeLine,
  EXTENSION_LOCKED_HINT,
  extensionLocked,
  groupAmendments,
  rateUnit,
  savedAt,
  useMkAnnexDocuments,
  type MkAnnexDocument,
} from "./AneksyA";
import { warsawDay } from "./DokumentyA";
import type { TabProps } from "./types";

const TD = "py-2 pr-3 align-top text-[13px] leading-5";

function DocCell({ a }: { a: MkAmendment }) {
  const doc = a.document as { id: number; filename: string; is_signed_scan: boolean } | null | undefined;
  if (doc) {
    return (
      <>
        <button type="button" title={doc.filename} className="inline-flex max-w-full items-center gap-1 text-primary hover:underline">
          <Paperclip className="size-3.5 shrink-0" aria-hidden />
          {/* Kolumna jest wąska — rodzaj pliku zamiast uciętej nazwy, pełna nazwa w podpowiedzi. */}
          <span className="truncate">{doc.filename.split(".").pop()?.toUpperCase() ?? "plik"}</span>
        </button>
        {a.source === "generator" && !doc.is_signed_scan ? <span className={CALM_SUBLINE}>bez podpisów · dołącz skan</span> : null}
      </>
    );
  }
  return (
    <button
      type="button"
      title="Dołącz skan aneksu do tego wpisu"
      className="text-[12.5px] text-muted-foreground/70 hover:text-primary hover:underline"
    >
      Dodaj
    </button>
  );
}

function AnnexDocRow({ d }: { d: MkAnnexDocument }) {
  const change = annexChangeText(d.change);
  const waiting = d.state === "waiting";
  return (
    <tr className={cn(CALM_ROW, d.state === "cancelled" && "text-muted-foreground")}>
      <td className={cn(TD, "whitespace-nowrap pl-3 pr-2 tabular-nums")}>
        {d.effective_date ? fmtDate(d.effective_date) : <span className={CALM_EMPTY}>—</span>}
      </td>
      <td className={cn(TD, "pr-2")}>
        <span className="block truncate font-medium" title={annexTitle(d.document_type)}>
          {annexTitle(d.document_type)}
        </span>
        <span className={cn(CALM_SUBLINE, waiting && "text-warning")}>
          {waiting ? "czeka na podpis" : d.state === "cancelled" ? "anulowany" : "podpisany"}
        </span>
      </td>
      <td className={cn(TD, "tabular-nums")}>
        <span className="block truncate">
          {change ? `${change.before ? `${change.before} → ` : ""}${change.after}` : <span className={CALM_EMPTY}>—</span>}
        </span>
        <span className={CALM_SUBLINE}>{waiting ? "zmieni kontrakt po podpisie" : d.cancelled_reason ?? ""}</span>
      </td>
      <td className={TD}>
        <span className={CALM_EMPTY}>{waiting ? "po podpisie" : "—"}</span>
      </td>
      <td className={cn(TD, "pr-3.5 text-[12.5px]")}>
        <span className="block">{d.created_by_name ?? "—"}</span>
        {d.created_at ? <span className={CALM_SUBLINE}>{fmtDate(warsawDay(d.created_at))}</span> : null}
      </td>
    </tr>
  );
}

export function AneksyB({ contractId }: TabProps) {
  const c = useMkContract(contractId).data;
  const amendQ = useMkAmendments(contractId);
  const annexQ = useMkAnnexDocuments(contractId);
  if (!c) return null;

  const unit = rateUnit(c);
  const locked = extensionLocked(c);
  const groups = groupAmendments(amendQ.data ?? []);
  const annexDocs = annexQ.data ?? [];
  const waiting = annexDocs.filter((d) => d.state === "waiting");
  const otherDocs = annexDocs.filter((d) => d.state !== "waiting");
  const empty = amendQ.isSuccess && annexQ.isSuccess && groups.length === 0 && annexDocs.length === 0;

  return (
    <div className="space-y-2.5">
      <div className="flex items-center gap-1.5">
        <Button type="button" variant="outline" size="sm">
          Zmień stawkę
        </Button>
        {/* Wyłączony przycisk nie dostaje najechania — podpowiedź wisi na opakowaniu. */}
        <span title={locked ? EXTENSION_LOCKED_HINT : undefined} className="inline-flex">
          <Button type="button" variant="outline" size="sm" disabled={locked} aria-describedby={locked ? "aneksy-b-lock" : undefined}>
            Przedłuż
          </Button>
        </span>
        {locked ? (
          <span id="aneksy-b-lock" className="sr-only">
            {EXTENSION_LOCKED_HINT}
          </span>
        ) : null}
        <Button type="button" variant="outline" size="sm">
          Zmień zakres
        </Button>
        <Button type="button" variant="outline" size="sm" title="Generator aneksów — dokument do podpisu, zmiana w kontrakcie po podpisie">
          Dokument aneksu
        </Button>
        <Button type="button" variant="quiet" size="sm" className="ml-auto">
          Zakończ wcześniej…
        </Button>
      </div>

      {amendQ.isLoading ? (
        <p className="text-sm text-muted-foreground">Ładowanie aneksów…</p>
      ) : amendQ.isError ? (
        <QueryStateNotice state="error" description="Nie udało się wczytać aneksów kontraktu." onRetry={() => void amendQ.refetch()} />
      ) : empty ? (
        <p className="rounded-xl border border-border bg-card px-4 py-5 text-[13px] text-muted-foreground shadow-xs">
          Bez aneksów — stawki i okres są takie jak przy starcie. Zmianę zapiszesz przyciskami wyżej.
        </p>
      ) : (
        <div className="overflow-hidden rounded-xl border border-border bg-card shadow-xs">
          {annexQ.isError ? (
            <p role="alert" className="border-b border-border/60 bg-destructive/10 px-3.5 py-2 text-[12.5px] text-destructive">
              Nie udało się wczytać aneksów czekających na podpis — tabela pokazuje tylko zmiany zapisane w kontrakcie.
            </p>
          ) : null}
          <table className="w-full table-fixed">
            <colgroup>
              <col className="w-[96px]" />
              <col className="w-[104px]" />
              <col />
              <col className="w-[72px]" />
              <col className="w-[142px]" />
            </colgroup>
            <thead>
              <tr className="border-b border-border text-left">
                <th scope="col" className={cn(CALM_HEAD, "py-2 pl-3 pr-2")}>
                  Od
                </th>
                <th scope="col" className={cn(CALM_HEAD, "py-2 pr-2")}>
                  Rodzaj
                </th>
                <th scope="col" className={cn(CALM_HEAD, "py-2 pr-3")}>
                  Zmiana
                  <span className={CALM_UNIT}>stawki w {unit}</span>
                </th>
                <th scope="col" className={cn(CALM_HEAD, "py-2 pr-2")}>
                  Dokument
                </th>
                <th scope="col" className={cn(CALM_HEAD, "py-2 pr-3.5")}>
                  Kto
                </th>
              </tr>
            </thead>
            <tbody>
              {waiting.map((d) => (
                <AnnexDocRow key={`d-${d.document_id}`} d={d} />
              ))}
              {groups.map((g) => (
                <Fragment key={g.first.id}>
                  {[g.first, ...g.all.filter((x) => x.id !== g.first.id).reverse()].map((a) => {
                    const repeat = a.id !== g.first.id;
                    const change = changeLine(a, unit, true);
                    const reason = repeat ? null : g.reason;
                    return (
                      <tr
                        key={a.id}
                        className={cn(CALM_ROW, (repeat || a.withdrawn || a.state === "cancelled") && "text-muted-foreground")}
                      >
                        <td className={cn(TD, "whitespace-nowrap pl-3 pr-2 tabular-nums")}>
                          {a.effective_date ? fmtDate(a.effective_date) : <span className={CALM_EMPTY}>—</span>}
                        </td>
                        <td className={cn(TD, "pr-2")}>
                          <span className={cn("block truncate", !repeat && "font-medium text-foreground")}>
                            {amendmentTitle(a, true)}
                          </span>
                          {repeat ? (
                            <span className={CALM_SUBLINE} title={`Ta sama zmiana co wpis z ${savedAt(g.first.created_at)}`}>
                              powtórzony wpis
                            </span>
                          ) : a.withdrawn ? (
                            <span className={CALM_SUBLINE}>wycofane</span>
                          ) : a.state === "signed_pending" ? (
                            <span className={cn(CALM_SUBLINE, "text-info")}>wejdzie w życie</span>
                          ) : null}
                        </td>
                        <td className={cn(TD, "tabular-nums")}>
                          <span className={cn("block truncate", !repeat && "text-foreground")} title={change}>
                            {change || <span className={CALM_EMPTY}>—</span>}
                          </span>
                          {reason ? (
                            <span className={cn(CALM_SUBLINE, "truncate")} title={reason}>
                              „{reason}”
                            </span>
                          ) : null}
                          {a.withdrawable ? (
                            <button type="button" className="mt-0.5 text-[12px] font-medium text-primary hover:underline">
                              Wycofaj wypowiedzenie
                            </button>
                          ) : null}
                        </td>
                        <td className={TD}>{repeat ? <span className={CALM_EMPTY}>—</span> : <DocCell a={a} />}</td>
                        <td className={cn(TD, "pr-3.5 text-[12.5px]")}>
                          <span className={cn("block", !repeat && "text-foreground")}>{authorOf(a)}</span>
                          <span className={CALM_SUBLINE} title={savedAt(a.created_at)}>
                            {fmtDate(warsawDay(a.created_at))}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </Fragment>
              ))}
              {otherDocs.map((d) => (
                <AnnexDocRow key={`d-${d.document_id}`} d={d} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-[12px] text-muted-foreground">
        Aneks z generatora zmienia kontrakt dopiero po podpisie; aneks dodany tutaj działa od razu.
      </p>
    </div>
  );
}
