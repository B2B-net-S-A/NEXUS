"use client";

import { ExternalLink } from "lucide-react";

import { TruncatedText } from "@/components/ds/TruncatedText";
import { safeHref } from "@/components/sales/format";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { SIGNAL_STRENGTH_LABELS, signalPayload, useLeads } from "@/lib/api/sales";
import { formatIsoDatePl } from "@/lib/date-pl";
import { hasPermission } from "@/lib/permissions";
import { useAuthStore } from "@/store/auth";

import { SignalActions } from "./SignalActions";

/**
 * Pas „Nowy sygnał” nad zakładkami karty firmy (G2): najmocniejszy nowy sygnał
 * z bota. Bez sygnału, z wyłączonym kanałem i przy błędzie zapytania pas nie
 * istnieje: to dodatek do karty, a nie jej stan.
 */
export function SignalStrip({ companyId }: { companyId: number }) {
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const leads = useLeads({ status: "new", source: "research", company_id: companyId, limit: 1 });
  const lead = leads.data?.signals_enabled ? leads.data.items[0] : undefined;
  if (!lead) return null;
  const signal = signalPayload(lead);
  const href = safeHref(lead.url);
  return (
    <Card className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 px-3 py-2">
      <div className="min-w-0 flex-1 basis-96 leading-tight">
        <div className="flex min-w-0 items-center gap-2">
          <Badge variant="soft" size="sm" className="shrink-0">
            Nowy sygnał
          </Badge>
          <TruncatedText className="min-w-0 max-w-none text-sm font-medium text-foreground">{lead.title}</TruncatedText>
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {[signal.strength ? SIGNAL_STRENGTH_LABELS[signal.strength] : null, signal.published ? formatIsoDatePl(signal.published) : null]
            .filter(Boolean)
            .join(" · ")}
          {href && (
            <>
              {" · "}
              <a href={href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
                {signal.domain || "źródło"} <ExternalLink className="h-3 w-3" aria-hidden />
              </a>
            </>
          )}
        </p>
        {signal.why_now && <p className="mt-0.5 text-xs text-muted-foreground">Dlaczego teraz: {signal.why_now}</p>}
      </div>
      {canEdit && <SignalActions lead={lead} />}
    </Card>
  );
}
