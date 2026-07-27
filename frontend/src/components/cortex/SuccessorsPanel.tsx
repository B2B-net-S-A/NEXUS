"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CalendarClock,
  Loader2,
  RefreshCw,
  UserRoundCheck,
} from "lucide-react";
import {
  cortexApi,
  extractErrorMsg,
  type CortexEndingContract,
  type CortexSuccessors,
} from "@/lib/api";
import { EmptyState } from "@/components/ds/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AvailabilityBadge } from "@/components/cortex/shared";

const DAYS_OPTIONS = [7, 14, 30, 60, 90] as const;
const DEFAULT_DAYS = 30;

export function SuccessorsPanel() {
  const [days, setDays] = useState<number>(DEFAULT_DAYS);

  const { data, isLoading, isError, error, refetch } =
    useQuery<CortexSuccessors>({
      queryKey: ["cortex-successors", days],
      queryFn: async () => (await cortexApi.successors(days)).data,
    });

  return (
    <div className="space-y-4">
      <div className="bg-card dark:bg-muted rounded-2xl shadow-xs p-6 space-y-4">
        <div className="flex flex-wrap items-center gap-4">
          <div>
            <h3 className="font-semibold text-sm">Następcy</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              Kontrakty kończące się w wybranym oknie i dostępni kandydaci z
              nakładającym się stackiem (ranking po liczbie wspólnych technologii).
            </p>
          </div>
          <label className="inline-flex items-center gap-1.5 text-xs ml-auto">
            Okno
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="border border-border rounded-md bg-background px-2 py-1.5"
            >
              {DAYS_OPTIONS.map((d) => (
                <option key={d} value={d}>
                  {d} dni
                </option>
              ))}
            </select>
          </label>
        </div>

        {isError ? (
          <div className="space-y-3">
            <p className="flex items-center gap-2 text-sm text-destructive">
              <AlertTriangle className="w-4 h-4" />
              Nie udało się załadować następców.
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
            Ładowanie następców…
          </p>
        ) : data.ending_contracts.length === 0 ? (
          <EmptyState
            icon={CalendarClock}
            title="Brak kończących się kontraktów"
            description={`Żaden aktywny/kończący kontrakt nie kończy się w ciągu ${days} dni. Tabela contracts jest słabo wypełniona — to spodziewane.`}
          />
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">
              {data.ending_contracts.length.toLocaleString("pl-PL")} kontraktów
              w oknie {days} dni.
            </p>
            {data.ending_contracts.map((c) => (
              <EndingContractCard key={c.contract_id} contract={c} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function EndingContractCard({
  contract,
}: {
  contract: CortexEndingContract;
}) {
  return (
    <div className="rounded-xl border border-border p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-medium text-foreground">
            Kontrakt #{contract.contract_id}
          </span>
          <span className="text-muted-foreground">·</span>
          <a
            href={`/candidates/${contract.candidate_id}`}
            className="text-primary hover:underline underline-offset-2"
          >
            {contract.candidate_name || contract.candidate_lastname
              ? `${contract.candidate_name ?? ""} ${contract.candidate_lastname ?? ""}`.trim()
              : `konsultant #${contract.candidate_id}`}
          </a>
          <span className="text-muted-foreground">
            · {contract.client_name || `klient #${contract.client_id}`}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {contract.end_date ? (
            <Badge variant="warning" size="sm">
              <CalendarClock className="w-3 h-3" />
              koniec {new Date(contract.end_date).toLocaleDateString("pl-PL")}
            </Badge>
          ) : null}
          <Badge variant="outline" size="sm">
            {contract.skill_count} technologii
          </Badge>
        </div>
      </div>

      {contract.successors.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          Brak dostępnych następców z nakładającym się stackiem.
        </p>
      ) : (
        <ul className="space-y-1.5">
          {contract.successors.map((s) => {
            const fullName = `${s.name ?? ""} ${s.lastname ?? ""}`.trim() || "—";
            return (
              <li
                key={s.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-muted/40 px-3 py-2"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <UserRoundCheck className="w-4 h-4 text-primary shrink-0" />
                  <a
                    href={`/candidates/${s.id}`}
                    className="text-sm font-medium text-foreground hover:text-primary hover:underline underline-offset-2 truncate"
                  >
                    {fullName}
                  </a>
                </div>
                <div className="flex items-center gap-2">
                  <AvailabilityBadge status={s.availability_status} />
                  <Badge variant="soft" size="sm">
                    {s.overlap} wspólnych
                  </Badge>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
