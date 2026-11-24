"use client";

// „Dla księgowej” w „Przebiegu miesiąca”: trzy pytania głównej księgowej na
// zamknięcie miesiąca (mail „Rozliczenie lipca”, 24.08.2026) — faktury
// kontraktorów z KSeF nieprzyjęte przez Finanse, brakujące faktury (rezerwa
// kosztu) i przyjęte RCP bez faktury sprzedaży. Dziś pyta o to mailem
// ok. 20. dnia następnego miesiąca. Tylko odczyt.

import Link from "next/link";
import { Download } from "lucide-react";

import { InlineStats } from "@/components/ds/InlineStats";
import { Button } from "@/components/ui/button";
import type { MonthCloseClosing, MonthCloseClosingRow } from "@/lib/api/client-settlements";

import { mdText, monthLabel, pln } from "../settlements/format";

interface ClosingPanelProps {
  closing: MonthCloseClosing | undefined;
  month: string;
}

/** CSV rezerwy dla księgowej (średnik, przecinek dziesiętny — jak Excel PL). */
export function reserveCsv(rows: MonthCloseClosingRow[]): string {
  const cell = (v: string) => (/[;"\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  const num = (v: string | null) => (v == null ? "" : v.replace(".", ","));
  const lines = ["Klient;Osoba;Kontrakt;MD;Koszt netto"];
  for (const r of rows) {
    lines.push([cell(r.client), cell(r.person), String(r.contract_id), num(r.md), num(r.cost)].join(";"));
  }
  return lines.join("\n");
}

function download(name: string, text: string) {
  const blob = new Blob(["﻿" + text], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function settlementLink(r: MonthCloseClosingRow, month: string): string {
  return `/finance?view=settlements&stClient=${r.client_id}&stMonth=${month}&stContract=${r.contract_id}`;
}

function PeopleList({ title, rows, month, empty }: { title: string; rows: MonthCloseClosingRow[]; month: string; empty: string }) {
  return (
    <section className="rounded-xl border bg-card px-3 py-2.5">
      <h3 className="text-[13px] font-medium">
        {title} <span className="tabular-nums text-muted-foreground">{rows.length}</span>
      </h3>
      {rows.length === 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">{empty}</p>
      ) : (
        <ul className="mt-1.5 grid gap-x-4 gap-y-0.5 text-xs sm:grid-cols-2">
          {rows.slice(0, 40).map((r) => (
            <li key={`${r.client_id}-${r.contract_id}`} className="truncate">
              <Link href={settlementLink(r, month)} className="hover:underline">
                {r.person}
              </Link>{" "}
              <span className="text-muted-foreground">· {r.client}</span>
            </li>
          ))}
          {rows.length > 40 ? <li className="text-muted-foreground">i {rows.length - 40} innych</li> : null}
        </ul>
      )}
    </section>
  );
}

export function ClosingPanel({ closing, month }: ClosingPanelProps) {
  if (!closing) return null;
  const rows = closing.rows;
  return (
    <div className="space-y-2">
      <section className="rounded-xl border bg-card px-4 py-3">
        <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{monthLabel(month)} · dla księgowej</p>
        <InlineStats
          className="mt-1.5"
          stats={[
            { id: "ksef", label: "faktur kontraktorów w KSeF, RCP nieprzyjęte", value: closing.ksef_not_accepted },
            { id: "reserve", label: "brakujących faktur kontraktorów", value: closing.reserve_count },
            ...(closing.reserve_total != null
              ? [{ id: "reserve-total", label: "rezerwa kosztu (netto)", value: pln(closing.reserve_total) }]
              : []),
            { id: "sales", label: "przyjętych RCP bez faktury sprzedaży", value: closing.sales_waiting },
          ]}
        />
        {closing.reserve_without_cost ? (
          <p className="mt-1.5 text-[11px] text-warning-muted-foreground">
            {closing.reserve_without_cost} os. bez kosztu w rozliczeniu (brak stawki albo MD) — rezerwa ich nie obejmuje.
          </p>
        ) : null}
        {rows ? (
          <div className="mt-2">
            <Button size="sm" variant="outline" onClick={() => download(`rezerwy-kontraktorzy-${month}.csv`, reserveCsv(rows.reserve))}>
              <Download className="mr-1.5 size-3.5" /> Pobierz rezerwy (CSV)
            </Button>
          </div>
        ) : (
          <p className="mt-1.5 text-[11px] text-muted-foreground">Kwoty i osoby widzi tylko osoba z dostępem do kwot.</p>
        )}
      </section>
      {rows ? (
        <>
          <section className="relative overflow-x-auto rounded-xl border bg-card">
            <table className="w-full min-w-[640px] table-fixed text-[13px]">
              <colgroup>
                <col className="w-[30%]" />
                <col className="w-[34%]" />
                <col className="w-[14%]" />
                <col className="w-[22%]" />
              </colgroup>
              <thead className="border-b bg-muted/40 text-left text-[11px] text-muted-foreground">
                <tr>
                  <th className="px-3 py-1.5 font-medium">Rezerwa: osoba</th>
                  <th className="px-2 py-1.5 font-medium">Klient</th>
                  <th className="px-2 py-1.5 text-right font-medium">MD</th>
                  <th className="px-3 py-1.5 text-right font-medium">Koszt netto</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {rows.reserve.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-3 py-4 text-center text-muted-foreground">
                      Wszystkie rozliczenia z MD mają fakturę kontraktora w KSeF.
                    </td>
                  </tr>
                ) : (
                  rows.reserve.slice(0, 200).map((r) => (
                    <tr key={`${r.client_id}-${r.contract_id}`}>
                      <td className="truncate px-3 py-1.5">
                        <Link href={settlementLink(r, month)} className="hover:underline">
                          {r.person}
                        </Link>
                      </td>
                      <td className="truncate px-2 py-1.5 text-muted-foreground">{r.client}</td>
                      <td className="px-2 py-1.5 text-right tabular-nums">{mdText(r.md)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{r.cost ? pln(r.cost) : "—"}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </section>
          <div className="grid gap-2 md:grid-cols-2">
            <PeopleList
              title="Faktura w KSeF, RCP nieprzyjęte"
              rows={rows.ksef_not_accepted}
              month={month}
              empty="Każda faktura kontraktora z KSeF ma przyjęte RCP."
            />
            <PeopleList
              title="Przyjęte RCP bez faktury sprzedaży"
              rows={rows.sales_waiting}
              month={month}
              empty="Każde przyjęte RCP ma fakturę do klienta."
            />
          </div>
        </>
      ) : null}
    </div>
  );
}
