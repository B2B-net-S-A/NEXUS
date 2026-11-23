"use client";

// Pasek kroków miesiąca nad tabelą jednego klienta (makiety 23.11.2026):
// raporty → RCP → faktury kontraktorów → faktura do klienta, plus trzy
// najczęstsze powody „do decyzji”. Liczy z odpowiedzi `useSettlementMonth`.

import Link from "next/link";

import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import type { SettlementRow } from "@/lib/api/client-settlements";

interface ClientMonthStripProps {
  rows: SettlementRow[];
  month: string;
}

interface Step {
  label: string;
  value: string;
  tone: StatusDotTone;
  note: string;
}

export function monthSteps(rows: SettlementRow[]): Step[] {
  const n = (pred: (r: SettlementRow) => boolean) => rows.filter(pred).length;
  const clean = n((r) => r.status === "ok" || r.status === "accepted");
  const accepted = n((r) => r.status === "accepted");
  const decide = n((r) => r.status === "warnings" || r.status === "needs_fix");
  const unread = n((r) => r.status === "checking" || r.status === "no_md");
  const missing = n((r) => r.status === "missing");
  const inKsef = n((r) => r.contractor_invoice === "in_ksef");
  const issued = n((r) => r.client_invoice === "issued");
  const ready = n((r) => r.client_invoice === "ready");
  return [
    {
      label: "Raporty",
      value: `${rows.length - missing} z ${rows.length}`,
      tone: missing ? "warning" : "success",
      note: missing ? `${missing} bez raportu w poczcie` : "komplet",
    },
    {
      label: "RCP",
      value: `${clean} bez uwag`,
      tone: decide + unread ? "warning" : "success",
      note: `${decide} do decyzji · ${unread} bez MD · ${accepted} przyjęte`,
    },
    {
      label: "Faktury kontraktorów",
      value: `${inKsef} w KSeF`,
      tone: rows.length && inKsef === rows.length ? "success" : "neutral",
      note: "po przyjęciu RCP",
    },
    {
      label: "Faktura do klienta",
      value: issued ? `${issued} wystawione` : ready ? `${ready} do wystawienia` : "czeka",
      tone: issued ? "info" : "neutral",
      note: ready ? "Wystaw za miesiąc" : "pozycje po przyjęciu RCP",
    },
  ];
}

export function topReasons(rows: SettlementRow[], limit = 3): [string, number][] {
  const reasons = new Map<string, number>();
  for (const r of rows) {
    if ((r.status === "warnings" || r.status === "needs_fix") && r.issues) {
      reasons.set(r.issues, (reasons.get(r.issues) ?? 0) + 1);
    }
  }
  return [...reasons.entries()].sort((a, b) => b[1] - a[1]).slice(0, limit);
}

export function ClientMonthStrip({ rows, month }: ClientMonthStripProps) {
  if (rows.length === 0) return null;
  const steps = monthSteps(rows);
  const reasons = topReasons(rows);
  return (
    <section className="rounded-xl border bg-card px-3 py-2.5">
      <ol className="grid grid-cols-2 gap-2 md:grid-cols-4">
        {steps.map((s, i) => (
          <li key={s.label} className="flex min-w-0 items-start gap-2">
            <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-muted text-[11px] font-semibold tabular-nums">
              {i + 1}
            </span>
            <span className="min-w-0">
              <span className="block truncate text-xs font-medium">{s.label}</span>
              <StatusDot
                tone={s.tone}
                className="max-w-full"
                note={
                  s.note === "Wystaw za miesiąc" ? (
                    <Link href={`/finance?view=sales-invoices&siPeriod=${month}&siView=issue`} className="text-primary hover:underline">
                      {s.note}
                    </Link>
                  ) : (
                    <span className="block truncate">{s.note}</span>
                  )
                }
              >
                {s.value}
              </StatusDot>
            </span>
          </li>
        ))}
      </ol>
      {reasons.length ? (
        <p className="mt-2 truncate border-t pt-2 text-[11px] text-muted-foreground">
          Najczęstsze powody do decyzji:{" "}
          {reasons.map(([reason, count]) => (
            <span key={reason} className="mr-3 font-medium text-foreground">
              {reason} <span className="tabular-nums text-muted-foreground">×{count}</span>
            </span>
          ))}
        </p>
      ) : null}
    </section>
  );
}
