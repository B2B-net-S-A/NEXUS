"use client";

import { PhoneCall } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { useCompanyCallRecords, type CompanyCallRecord } from "@/lib/api/sales-calling";
import { formatDayMonthPl } from "@/lib/date-pl";

import { STATE_TONES, stateLabel } from "./calling";

function returnText(row: CompanyCallRecord): string | null {
  if (row.state === "meeting_booked" || row.state === "do_not_contact" || row.state === "bad_contact") return null;
  if (row.state === "not_interested" && !row.callback_on) return "nie wraca";
  return row.callback_on ? `wraca ${formatDayMonthPl(row.callback_on)}` : null;
}

/**
 * „Na liście dzwonienia” na karcie firmy (decyzja Artura 12.11.2026): handlowiec widzi, że do
 * firmy dzwoni ktoś z kampanii, z jakim wynikiem i kiedy wraca. Bez numeru telefonu.
 * Brak rekordów albo błąd zapytania: nic, bo to dodatek do karty, nie jej treść.
 */
export function CompanyCallLists({ companyId }: { companyId: number }) {
  const records = useCompanyCallRecords(companyId);
  const rows = records.data ?? [];
  if (!records.isSuccess || rows.length === 0) return null;
  return (
    <section aria-label="Na liście dzwonienia" className="rounded-lg border border-border bg-card px-3 py-2 text-sm">
      <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        <PhoneCall className="h-3.5 w-3.5" aria-hidden /> Na liście dzwonienia
      </p>
      <ul className="mt-1 space-y-1">
        {rows.map((row) => {
          const back = returnText(row);
          return (
            <li key={row.record_id} className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <span className="font-medium text-foreground">{row.assignee?.name ?? "Bez osoby"}</span>
              {row.campaign && <span className="text-muted-foreground">· {row.campaign.name}</span>}
              <Badge variant={STATE_TONES[row.state]} size="sm">
                {stateLabel(row.state)}
              </Badge>
              {back && <span className="text-xs text-muted-foreground">{back}</span>}
              {row.person_name && <span className="text-xs text-muted-foreground">· {row.person_name}</span>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
