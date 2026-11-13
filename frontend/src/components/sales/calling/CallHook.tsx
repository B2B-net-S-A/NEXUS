"use client";

import { ExternalLink } from "lucide-react";

import { safeHref } from "@/components/sales/format";
import { useCompanyBriefing } from "@/lib/api/sales";
import { formatIsoDatePl } from "@/lib/date-pl";

/**
 * Haczyk przed telefonem: zdanie otwarcia od bota researchu i do dwóch faktów ze
 * źródłem. Bot przygotowuje go dzień roboczy wcześniej. Bez haczyka, z wyłączonymi
 * zadaniami bota, w trakcie wczytywania i przy błędzie nic nie pokazuje: to podpowiedź,
 * nie warunek rozmowy.
 */
export function CallHook({ companyId }: { companyId: number }) {
  const query = useCompanyBriefing(companyId);
  const hook = query.isSuccess && query.data.enabled ? query.data.call_hook : null;
  if (!hook) return null;
  return (
    <section
      className="space-y-1 rounded-md border border-border bg-muted/30 px-2.5 py-2"
      aria-label="Haczyk do rozmowy"
      data-tour="sales.calling.hook"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-xs font-medium text-foreground">Na otwarcie</h3>
      </div>
      <p className="text-sm leading-snug text-foreground">{hook.sentence}</p>
      <ul className="space-y-0.5">
        {hook.facts.map((fact, index) => {
          const href = safeHref(fact.url);
          return (
            <li key={index} className="text-xs leading-snug text-muted-foreground">
              {fact.text}
              {fact.published && <span className="tabular-nums"> · {formatIsoDatePl(fact.published)}</span>}
              {href && (
                <a
                  href={href}
                  target="_blank"
                  rel="noreferrer"
                  className="ml-1 inline-flex items-center gap-0.5 text-primary hover:underline"
                >
                  źródło <ExternalLink className="h-3 w-3" aria-hidden />
                </a>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
