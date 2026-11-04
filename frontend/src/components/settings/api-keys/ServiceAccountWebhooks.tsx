"use client";

import { useId } from "react";
import { ChevronDown, Loader2 } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { formatDateTimePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import { webhookEventsLabel, webhookState } from "./api-keys-model";
import type { AccountWebhooksState } from "./types";

export interface ServiceAccountWebhooksProps {
  accountName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  state: AccountWebhooksState | undefined;
}

/** Webhooki konta (zakłada je automatyzacja kluczem przez API v1) — odczyt
 *  dla admina, zwinięty, dopóki ktoś go nie otworzy. Adres bez parametrów
 *  zapytania: odbiorca trzyma w nich własne tokeny. */
export function ServiceAccountWebhooks({
  accountName,
  open,
  onOpenChange,
  state,
}: ServiceAccountWebhooksProps) {
  const panelId = useId();

  return (
    <section className="space-y-2">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => onOpenChange(!open)}
        className="inline-flex items-center gap-1.5 text-sm font-semibold text-foreground hover:text-primary"
      >
        <ChevronDown
          className={cn("size-4 transition-transform", open ? "rotate-0" : "-rotate-90")}
          aria-hidden
        />
        Webhooki
      </button>

      {open ? (
        <div id={panelId}>
          {!state || state.status === "loading" ? (
            <p className="flex items-center gap-2 py-3 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" aria-hidden />
              Pobieram webhooki…
            </p>
          ) : state.status === "error" ? (
            <QueryStateNotice state="error" description={state.message} onRetry={state.onRetry} className="py-6" />
          ) : state.webhooks.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border px-3 py-4 text-sm text-muted-foreground">
              To konto nie ma webhooków. Automatyzacja zakłada je sama przez API (<code>POST /webhooks</code>).
            </p>
          ) : (
            <div className="relative overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[720px] text-sm">
                <caption className="sr-only">Webhooki konta {accountName}</caption>
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th scope="col" className="sticky left-0 z-10 bg-card px-3 py-2 font-medium">
                      Adres
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Zdarzenia
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Stan
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Ostatnia wysyłka
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {state.webhooks.map((hook) => {
                    const view = webhookState(hook);
                    return (
                      <tr key={hook.id} className="border-b border-border align-top last:border-b-0">
                        <th
                          scope="row"
                          className="sticky left-0 z-10 bg-card px-3 py-2 text-left font-mono text-xs font-normal [overflow-wrap:anywhere]"
                        >
                          {hook.url}
                        </th>
                        <td className="px-3 py-2 text-xs [overflow-wrap:anywhere]">
                          {webhookEventsLabel(hook.event_types)}
                        </td>
                        <td className="px-3 py-2">
                          <Badge variant={view.tone} size="sm" className="whitespace-normal text-left">
                            {view.label}
                          </Badge>
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap tabular-nums">
                          {hook.last_delivery_at ? (
                            <>
                              {formatDateTimePl(hook.last_delivery_at)}
                              {hook.last_status != null ? ` · ${hook.last_status}` : ""}
                            </>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}
