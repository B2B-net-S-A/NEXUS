"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Building2, Loader2, RefreshCw } from "lucide-react";
import {
  cortexApi,
  extractErrorMsg,
  type CortexClientStack,
} from "@/lib/api";
import { EmptyState } from "@/components/ds/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const MIN_COUNT_OPTIONS = [1, 2, 3, 5] as const;
const DEFAULT_MIN_COUNT = 2;

type ClientGroup = {
  id: number;
  name: string;
  consultants: number;
  skills: { skill: string; count: number }[];
};

/** Group flat cells into per-client stacks, ordered by embedded consultants. */
function groupByClient(data: CortexClientStack): ClientGroup[] {
  const skillsByClient = new Map<number, { skill: string; count: number }[]>();
  for (const cell of data.cells) {
    const list = skillsByClient.get(cell.client_id) ?? [];
    list.push({ skill: cell.skill, count: cell.count });
    skillsByClient.set(cell.client_id, list);
  }
  // `clients` already arrives sorted by consultants desc.
  return data.clients.map((c) => ({
    id: c.id,
    name: c.name,
    consultants: c.consultants,
    skills: (skillsByClient.get(c.id) ?? []).sort((a, b) => b.count - a.count),
  }));
}

export function ClientStackPanel() {
  const [minCount, setMinCount] = useState<number>(DEFAULT_MIN_COUNT);
  const [clientId, setClientId] = useState<number | "">("");

  const { data, isLoading, isError, error, refetch } =
    useQuery<CortexClientStack>({
      // Fetch the full matrix (no server client filter) so the dropdown keeps
      // every client; the client filter below is applied client-side.
      queryKey: ["cortex-client-stack", minCount],
      queryFn: async () =>
        (await cortexApi.clientStack({ min_count: minCount })).data,
    });

  const groups = useMemo(() => (data ? groupByClient(data) : []), [data]);
  const visible = useMemo(
    () => (clientId === "" ? groups : groups.filter((g) => g.id === clientId)),
    [groups, clientId]
  );

  const pairCount = data?.cells.length ?? 0;

  return (
    <div className="space-y-4">
      <div className="bg-card dark:bg-muted rounded-2xl shadow-xs p-6 space-y-4">
        <div className="flex flex-wrap items-center gap-4">
          <div>
            <h3 className="font-semibold text-sm">Klient × stack</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              Kto z naszych konsultantów siedzi u klienta i z jakim stackiem —
              wejście do cross-sellu i spotkań sprzedażowych.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs ml-auto">
            <label className="inline-flex items-center gap-1.5">
              Klient
              <select
                value={clientId === "" ? "" : String(clientId)}
                onChange={(e) =>
                  setClientId(e.target.value ? Number(e.target.value) : "")
                }
                className="border border-border rounded-md bg-background px-2 py-1.5 max-w-[16rem]"
              >
                <option value="">Wszyscy klienci</option>
                {groups.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name} ({g.consultants})
                  </option>
                ))}
              </select>
            </label>
            <label className="inline-flex items-center gap-1.5">
              Min. konsultantów
              <select
                value={minCount}
                onChange={(e) => {
                  setMinCount(Number(e.target.value));
                  setClientId("");
                }}
                className="border border-border rounded-md bg-background px-2 py-1.5"
              >
                {MIN_COUNT_OPTIONS.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        {isError ? (
          <div className="space-y-3">
            <p className="flex items-center gap-2 text-sm text-destructive">
              <AlertTriangle className="w-4 h-4" />
              Nie udało się załadować macierzy klient × stack.
            </p>
            <p className="text-xs text-muted-foreground">
              {extractErrorMsg(error)}
            </p>
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              <RefreshCw className="w-3.5 h-3.5" />
              Spróbuj ponownie
            </Button>
          </div>
        ) : isLoading || !data ? (
          <p className="text-sm text-muted-foreground">
            <Loader2 className="w-4 h-4 animate-spin inline mr-2" />
            Ładowanie macierzy…
          </p>
        ) : visible.length === 0 ? (
          <EmptyState
            icon={Building2}
            title="Brak osadzeń u klientów"
            description="Żaden klient nie przekracza progu min. konsultantów przy tym filtrze. „Osadzenie” = aktywny kontrakt lub ostatni etap „hired” — populacja bywa mała."
          />
        ) : (
          <>
            <p className="text-xs text-muted-foreground">
              {groups.length.toLocaleString("pl-PL")} klientów ·{" "}
              {pairCount.toLocaleString("pl-PL")} par klient×technologia
              {clientId !== "" ? " · filtr: 1 klient" : ""}
            </p>
            <div className="grid gap-4 md:grid-cols-2">
              {visible.map((g) => (
                <ClientCard key={g.id} group={g} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function ClientCard({ group }: { group: ClientGroup }) {
  return (
    <div className="rounded-xl border border-border p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 text-primary shrink-0">
            <Building2 className="h-3.5 w-3.5" />
          </span>
          <span className="font-medium text-sm text-foreground truncate">
            {group.name}
          </span>
        </div>
        <Badge variant="soft" size="sm">
          {group.consultants.toLocaleString("pl-PL")} konsult.
        </Badge>
      </div>
      {group.skills.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          Brak technologii nad progiem.
        </p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {group.skills.map((s) => (
            <Badge key={s.skill} variant="outline" size="sm">
              {s.skill}
              <span className="tabular-nums text-muted-foreground">
                · {s.count}
              </span>
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
