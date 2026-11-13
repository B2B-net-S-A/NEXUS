"use client";

import Link from "next/link";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Card } from "@/components/ui/card";
import { useCompanyBotHistory } from "@/lib/api/sales-bot";

import { SourceLink } from "./kit";

function formatAt(iso: string): string {
  return new Date(iso).toLocaleString("pl-PL", {
    timeZone: "Europe/Warsaw",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Historia karty: co boty wpisały od razu, co zostawiły i skąd to wzięły.
 * Jedyne miejsce, gdzie widać, że wartość wpisał automat (decyzja Artura
 * z 13.11.2026). Bez wpisów i z wyłączoną flagą nic nie pokazuje.
 */
export function BotCardHistory({ companyId }: { companyId: number }) {
  const history = useCompanyBotHistory(companyId);
  if (history.isError) {
    return (
      <Card className="p-4">
        <QueryStateNotice
          state="error"
          description="Nie udało się wczytać historii zmian karty."
          onRetry={() => void history.refetch()}
        />
      </Card>
    );
  }
  if (!history.isSuccess || !history.data.enabled || history.data.items.length === 0) return null;
  return (
    <Card className="space-y-3 p-4" aria-label="Historia zmian karty">
      <h2 className="text-sm font-semibold text-foreground">Historia zmian karty</h2>
      {history.data.items.map((entry, index) => (
        <section key={`${entry.at}-${index}`} className="space-y-1">
          <p className="text-xs text-muted-foreground">
            <span className="tabular-nums">{formatAt(entry.at)}</span> · {entry.bot} (automat)
          </p>
          <ul className="space-y-0.5">
            {entry.lines.map((line, lineIndex) => (
              <li key={`${line.label}-${lineIndex}`} className="text-xs leading-snug text-foreground">
                <span className="font-medium">{line.label}:</span>{" "}
                {line.before && (
                  <>
                    <span className="text-muted-foreground line-through">{line.before}</span>
                    {" → "}
                  </>
                )}
                {line.after ?? "—"}
                {line.note && <span className="text-muted-foreground"> · {line.note}</span>}
                {line.other_company && (
                  <>
                    {" "}
                    <Link href={`/sales/companies/${line.other_company.id}`} className="text-primary hover:underline">
                      {line.other_company.name}
                    </Link>
                  </>
                )}
                {line.source && (
                  <span className="ml-1 inline-block">
                    <SourceLink url={line.source} />
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </Card>
  );
}
