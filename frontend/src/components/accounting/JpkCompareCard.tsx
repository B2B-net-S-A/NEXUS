"use client";

import { useRef, useState } from "react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useCompareJpk, useJpk, type JpkCompareResult, type JpkCompareRows } from "@/lib/api/accounting-vat";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { SectionCard } from "./AccountingShell";
import { gr } from "./ledger-model";

const KIND_LABEL: Record<JpkCompareRows["kind"], string> = { sales: "Sprzedaż", purchases: "Zakup" };
const LIST_SHOWN = 20;

/**
 * Porównanie JPK_V7M z NEXUSA z plikiem z Symfonii (K5b-3b): w miesiącach
 * równoległych różnice pól deklaracji i wierszy (tylko w NEXUSIE, tylko
 * w Symfonii, inne kwoty albo znaczniki). Pliku serwer nie zapisuje.
 */
export function JpkCompareCard({ year, month }: { year: number; month: number }) {
  const { showToast } = useToast();
  const jpk = useJpk(year, month);
  const compare = useCompareJpk();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<JpkCompareResult | null>(null);
  const run = () => {
    if (!file) return;
    compare.mutate(
      { year, month, file },
      {
        onSuccess: (data) => setResult(data),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się porównać pliku."), "error"),
      },
    );
  };
  // Plik z Symfonii ma faktury osób zespołu — karta tylko dla osób, które pobierają JPK.
  if (!jpk.isSuccess || !jpk.data.can_download) return null;
  return (
    <SectionCard title="Porównanie z JPK z Symfonii" aside="miesiące równoległe · plik nie jest zapisywany">
      <div className="flex flex-wrap items-center gap-2.5 px-3.5 py-2.5 text-[13px]">
        <input
          ref={input}
          type="file"
          accept=".xml,application/xml,text/xml"
          aria-label="Plik JPK z Symfonii"
          className="w-full max-w-xs text-[13px]"
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
            setResult(null);
          }}
        />
        <Button size="sm" variant="outline" disabled={!file} loading={compare.isPending} onClick={run}>
          Porównaj
        </Button>
      </div>
      {result ? <CompareResult result={result} /> : null}
    </SectionCard>
  );
}

function CompareResult({ result }: { result: JpkCompareResult }) {
  const fields = result.declaration.filter((item) => item.nexus !== item.symfonia);
  return (
    <div className="space-y-2.5 border-t border-border/70 px-3.5 py-2.5 text-[13px]">
      <p className={result.differences ? "font-medium text-warning-muted-foreground" : "font-medium text-success-muted-foreground"}>
        {result.differences ? `Różnice: ${result.differences}` : "Pliki zgodne — wiersze i pola deklaracji takie same."}
      </p>
      {fields.length ? (
        <table className="w-full max-w-md table-fixed text-sm">
          <thead>
            <tr className="border-b border-border/70">
              <th className={cn(CALM_HEAD, "py-1.5 text-left")}>Pole deklaracji</th>
              <th className={cn(CALM_HEAD, "py-1.5 text-right")}>NEXUS</th>
              <th className={cn(CALM_HEAD, "py-1.5 text-right")}>Symfonia</th>
            </tr>
          </thead>
          <tbody>
            {fields.map((item) => (
              <tr key={item.field} className={CALM_ROW}>
                <td className="py-1 tabular-nums">{item.field}</td>
                <td className={cn(CALM_AMOUNT, "py-1 text-right")}>{item.nexus}</td>
                <td className={cn(CALM_AMOUNT, "py-1 text-right")}>{item.symfonia}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {result.rows.map((rows) => (
        <RowsDiff key={rows.kind} rows={rows} />
      ))}
    </div>
  );
}

function RowsDiff({ rows }: { rows: JpkCompareRows }) {
  const label = KIND_LABEL[rows.kind];
  return (
    <div className="space-y-1">
      <p className="font-medium">
        {label}: NEXUS {rows.nexus_rows} · Symfonia {rows.symfonia_rows} · zgodne {rows.matched}
      </p>
      {rows.only_nexus_count ? (
        <Listing title={`Tylko w NEXUSIE: ${rows.only_nexus_count}`} items={rows.only_nexus.map((item) => `${item.number} — ${item.party}, VAT ${gr(item.vat)} zł`)} />
      ) : null}
      {rows.only_symfonia_count ? (
        <Listing title={`Tylko w Symfonii: ${rows.only_symfonia_count}`} items={rows.only_symfonia.map((item) => `${item.number} — ${item.party}, VAT ${gr(item.vat)} zł`)} />
      ) : null}
      {rows.different_count ? (
        <Listing
          title={`Inne kwoty albo znaczniki: ${rows.different_count}`}
          items={rows.different.map((item) => {
            const amounts = Object.entries(item.fields).map(([field, pair]) => `${field}: ${gr(pair.nexus)} / ${gr(pair.symfonia)}`);
            const marks = item.markers ? [`znaczniki: ${item.markers.nexus.join(", ") || "brak"} / ${item.markers.symfonia.join(", ") || "brak"}`] : [];
            return `${item.number} — ${[...amounts, ...marks].join("; ")} (NEXUS / Symfonia)`;
          })}
        />
      ) : null}
    </div>
  );
}

function Listing({ title, items }: { title: string; items: string[] }) {
  return (
    <details className="text-[12px]">
      <summary className="cursor-pointer text-warning-muted-foreground">{title}</summary>
      <ul className="mt-1 space-y-0.5">
        {items.slice(0, LIST_SHOWN).map((item, index) => (
          <li key={`${item}:${index}`} className="tabular-nums">
            {item}
          </li>
        ))}
        {items.length > LIST_SHOWN ? <li className="text-muted-foreground">i {items.length - LIST_SHOWN} więcej</li> : null}
      </ul>
    </details>
  );
}
