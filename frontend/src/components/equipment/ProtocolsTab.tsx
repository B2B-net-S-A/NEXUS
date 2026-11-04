"use client";

import { useDeferredValue, useState } from "react";
import { MoreHorizontal, Search } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useProtocols, type ProtocolKind } from "@/lib/api/equipment";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { resolveViewState } from "@/lib/view-state";
import { formatIsoDatePl } from "@/lib/date-pl";

import {
  PROTOCOL_STATUS_LABELS,
  PROTOCOL_STATUS_TONE,
  SIGNATURE_LABELS,
  formatPln,
} from "./equipment-format";
import { FilterSelect } from "./FilterSelect";
import { useProtocolQuickActions } from "./useProtocolQuickActions";

type StatusFilter = "waiting" | "potwierdzony" | "anulowany";

const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: "waiting", label: "Czeka na podpis lub potwierdzenie" },
  { value: "potwierdzony", label: "Potwierdzone" },
  { value: "anulowany", label: "Anulowane" },
];

/**
 * Protokoły wydań i zwrotów; klik otwiera podpis, skan i pobranie. W ⋯ wiersza
 * „Popraw…” (przed podpisem) i „Anuluj protokół…” (przed potwierdzeniem).
 */
export function ProtocolsTab({
  onOpenProtocol,
  onCorrectProtocol,
}: {
  onOpenProtocol: (id: number) => void;
  onCorrectProtocol: (id: number) => void;
}) {
  const quick = useProtocolQuickActions();
  const [status, setStatus] = useState<StatusFilter | "">("waiting");
  const [kind, setKind] = useState<ProtocolKind | "">("");
  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query);
  const protocols = useProtocols(status, kind, deferred);
  const rows = protocols.data ?? [];
  const state = resolveViewState({
    isLoading: protocols.isLoading,
    error: protocols.error,
    isSuccess: protocols.isSuccess,
    isEmpty: rows.length === 0,
  });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full max-w-xs">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            aria-label="Szukaj protokołu"
            placeholder="Numer protokołu albo osoba…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="h-9 pl-8"
          />
        </div>
        <FilterSelect
          label="Stan protokołu"
          value={status}
          allLabel="Wszystkie"
          options={STATUS_OPTIONS}
          onChange={setStatus}
          className="h-9 w-auto min-w-64 gap-2 whitespace-nowrap"
        />
        <FilterSelect
          label="Rodzaj"
          value={kind}
          allLabel="Wydania i zwroty"
          options={[
            { value: "wydanie" as const, label: "Wydania" },
            { value: "zwrot" as const, label: "Zwroty" },
          ]}
          onChange={setKind}
        />
      </div>
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie protokołów…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => protocols.refetch()} />
      ) : state === "empty" ? (
        <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          {status === "waiting" ? "Żaden protokół nie czeka na podpis." : "Brak protokołów."}
        </div>
      ) : (
        <div className="relative overflow-x-auto rounded-lg border border-border bg-card">
          <Table density="compact" className="min-w-[820px]">
            <TableHeader>
              <TableRow>
                <TableHead className={CALM_HEAD}>Numer</TableHead>
                <TableHead className={CALM_HEAD}>Osoba</TableHead>
                <TableHead className={CALM_HEAD}>Data</TableHead>
                <TableHead className={CALM_HEAD}>Stan</TableHead>
                <TableHead className={CALM_HEAD}>Podpis</TableHead>
                <TableHead className={`${CALM_HEAD} text-right`}>Wartość</TableHead>
                <TableHead className="w-12">
                  <span className="sr-only">Akcje</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((protocol) => (
                <TableRow
                  key={protocol.id}
                  className={`${CALM_ROW} h-[46px] cursor-pointer hover:bg-muted/50`}
                  onClick={() => onOpenProtocol(protocol.id)}
                >
                  <TableCell>
                    <button
                      type="button"
                      className="font-mono text-xs text-foreground hover:underline"
                      onClick={(event) => {
                        event.stopPropagation();
                        onOpenProtocol(protocol.id);
                      }}
                    >
                      {protocol.number}
                    </button>
                    <span className={CALM_SUBLINE}>
                      {protocol.kind === "wydanie" ? "wydanie" : "zwrot"}
                    </span>
                  </TableCell>
                  <TableCell>{protocol.holder.name}</TableCell>
                  <TableCell>{formatIsoDatePl(protocol.protocol_date)}</TableCell>
                  <TableCell>
                    <StatusDot
                      tone={PROTOCOL_STATUS_TONE[protocol.status]}
                      note={
                        protocol.link && protocol.status === "oczekuje"
                          ? `link do ${formatIsoDatePl(protocol.link.expires_at)}`
                          : undefined
                      }
                    >
                      {PROTOCOL_STATUS_LABELS[protocol.status]}
                    </StatusDot>
                  </TableCell>
                  <TableCell className="text-xs">
                    {SIGNATURE_LABELS[protocol.signature_method]}
                  </TableCell>
                  <TableCell className={CALM_AMOUNT}>
                    {protocol.kind === "wydanie" ? formatPln(protocol.total_value) : "—"}
                  </TableCell>
                  <TableCell className="text-right" onClick={(event) => event.stopPropagation()}>
                    {protocol.status === "oczekuje" || protocol.status === "podpisany" ? (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            size="icon-sm"
                            variant="ghost"
                            aria-label={`Więcej akcji: ${protocol.number}`}
                          >
                            <MoreHorizontal className="h-4 w-4" aria-hidden />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          {protocol.status === "oczekuje" ? (
                            <DropdownMenuItem onSelect={() => onCorrectProtocol(protocol.id)}>
                              Popraw…
                            </DropdownMenuItem>
                          ) : null}
                          <DropdownMenuItem
                            className="text-destructive"
                            onSelect={() => void quick.cancelProtocol(protocol)}
                          >
                            Anuluj protokół…
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {quick.dialogs}
    </div>
  );
}
