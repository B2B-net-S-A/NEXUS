"use client";

import { useId } from "react";
import { ChevronDown, Loader2 } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import type { ServiceAccountKeyDto } from "@/lib/api";
import { formatDateTimePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import { writeStateLabel } from "./api-keys-model";
import type { AccountWritesState } from "./types";

function statusVariant(code: number | null): "success" | "warning" | "danger" | "outline" {
  if (code == null) return "outline";
  if (code >= 500) return "danger";
  if (code >= 400) return "warning";
  return "success";
}

export interface ServiceAccountWritesProps {
  accountName: string;
  keys: readonly ServiceAccountKeyDto[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  state: AccountWritesState | undefined;
}

/** „Ostatnie zapisy” konta przez API integracyjne v1 — zwinięte, dopóki ktoś
 *  ich nie otworzy (zapytanie startuje dopiero wtedy). */
export function ServiceAccountWrites({
  accountName,
  keys,
  open,
  onOpenChange,
  state,
}: ServiceAccountWritesProps) {
  const panelId = useId();
  const keyLabel = (keyId: string) => keys.find((k) => k.key_id === keyId)?.label ?? keyId;

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
        Ostatnie zapisy przez API
      </button>

      {open ? (
        <div id={panelId}>
          {!state || state.status === "loading" ? (
            <p className="flex items-center gap-2 py-3 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" aria-hidden />
              Pobieram zapisy…
            </p>
          ) : state.status === "error" ? (
            <QueryStateNotice state="error" description={state.message} onRetry={state.onRetry} className="py-6" />
          ) : state.writes.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border px-3 py-4 text-sm text-muted-foreground">
              To konto nie zapisało jeszcze nic przez API.
            </p>
          ) : (
            <div className="relative overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[720px] text-sm">
                <caption className="sr-only">Ostatnie zapisy konta {accountName}</caption>
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th scope="col" className="sticky left-0 z-10 bg-card px-3 py-2 font-medium">
                      Kiedy
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Metoda
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Trasa
                    </th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      Kod
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Stan
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Klucz
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {state.writes.map((write) => (
                    <tr key={write.id} className="border-b border-border align-top last:border-b-0">
                      <th
                        scope="row"
                        className="sticky left-0 z-10 bg-card px-3 py-2 text-left font-normal whitespace-nowrap tabular-nums"
                      >
                        {formatDateTimePl(write.created_at)}
                      </th>
                      <td className="px-3 py-2 font-mono text-xs">{write.method}</td>
                      <td className="px-3 py-2 font-mono text-xs [overflow-wrap:anywhere]">{write.route}</td>
                      <td className="px-3 py-2 text-right">
                        <Badge variant={statusVariant(write.status_code)} size="sm" className="tabular-nums">
                          {write.status_code ?? "—"}
                        </Badge>
                      </td>
                      <td className="px-3 py-2">{writeStateLabel(write.state)}</td>
                      <td className="px-3 py-2 [overflow-wrap:anywhere]">{keyLabel(write.key_id)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}
