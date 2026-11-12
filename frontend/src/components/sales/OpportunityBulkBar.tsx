"use client";

import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useBulkOpportunities,
  useOwnerCandidates,
  type OpportunityBulkAction,
  type OpportunityBulkResult,
} from "@/lib/api/sales";

import { STEP_WHEN } from "./CallLogDialogs";
import { plural } from "./my-day";
import { SalesSelect } from "./SalesSelect";

interface OpportunityBulkBarProps {
  ids: number[];
  /** Nazwa etapu przegranej w oglądanym lejku; bez niego nie ma „Zamknij z powodem”. */
  lostStageName: string | null;
  onClear: () => void;
}

const opportunities = (count: number) => plural(count, "szansę", "szanse", "szans");

/**
 * Akcje dla wielu zaznaczonych szans (decyzja Artura 11.11.2026): krok, opiekun, zamknięcie.
 * Reguły pojedynczej zmiany sprawdza backend dla każdej szansy; pominięte wracają z powodem.
 */
export function OpportunityBulkBar({ ids, lostStageName, onClear }: OpportunityBulkBarProps) {
  const run = useBulkOpportunities();
  const { showError, showSuccess } = useToast();
  // Ta sama lista co przy jednej szansie (`ChangeOwnerDialog`): aktywne konta z „Sprzedaż: edycja”.
  const candidates = useOwnerCandidates();
  const owners = (candidates.data ?? []).map((person) => ({ value: String(person.id), label: person.name }));
  const [owner, setOwner] = useState("");
  const [reason, setReason] = useState("");
  const [skipped, setSkipped] = useState<OpportunityBulkResult["skipped"]>([]);

  const send = (label: string, action: OpportunityBulkAction) =>
    run.mutate(
      { ids, ...action },
      {
        onSuccess: (result) => {
          if (result.done.length > 0) showSuccess(`${label}: ${opportunities(result.done.length)}.`);
          setSkipped(result.skipped);
          if (result.skipped.length === 0) onClear();
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać zaznaczonych szans.")),
      },
    );

  return (
    <div
      role="region"
      aria-label="Zaznaczone szanse"
      className="sticky top-0 z-20 space-y-1 rounded-lg border border-primary/40 bg-primary/5 px-3 py-2 text-sm"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-foreground">Zaznaczone: {opportunities(ids.length)}</span>
        <Popover>
          <PopoverTrigger asChild>
            <Button size="sm" variant="outline" disabled={run.isPending}>
              Zaplanuj krok
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto max-w-xs p-2">
            <p className="mb-1 text-xs text-muted-foreground">Zadzwonić…</p>
            <div className="flex flex-wrap gap-1">
              {STEP_WHEN.map((option) => (
                <Button
                  key={option.days}
                  size="sm"
                  variant="outline"
                  className="h-7 px-2"
                  disabled={run.isPending}
                  onClick={() => send(`Krok „Zadzwonić” ${option.label.toLowerCase()}`, { action: "plan", days: option.days })}
                >
                  {option.label}
                </Button>
              ))}
            </div>
          </PopoverContent>
        </Popover>
        <Popover>
          <PopoverTrigger asChild>
            <Button size="sm" variant="outline" disabled={run.isPending}>
              Zmień opiekuna
            </Button>
          </PopoverTrigger>
          <PopoverContent className="flex w-72 flex-col gap-2 p-3">
            {candidates.isError ? (
              <div role="alert" className="flex items-center justify-between gap-2 text-xs text-destructive">
                <span>{apiErrorMessage(candidates.error, "Nie udało się wczytać listy osób.")}</span>
                <Button size="sm" variant="outline" onClick={() => void candidates.refetch()}>
                  Spróbuj ponownie
                </Button>
              </div>
            ) : !candidates.isSuccess ? (
              <p className="text-xs text-muted-foreground">Wczytywanie osób…</p>
            ) : (
              <SalesSelect
                ariaLabel="Nowy opiekun"
                value={owner}
                onValueChange={setOwner}
                options={owners}
                anyLabel="Wybierz osobę"
              />
            )}
            <Button
              size="sm"
              disabled={!candidates.isSuccess || !owner || run.isPending}
              onClick={() => send("Zmieniono opiekuna", { action: "owner", owner_user_id: Number(owner) })}
            >
              Przekaż {opportunities(ids.length)}
            </Button>
          </PopoverContent>
        </Popover>
        {lostStageName && (
          <Popover>
            <PopoverTrigger asChild>
              <Button size="sm" variant="outline" disabled={run.isPending}>
                Zamknij z powodem
              </Button>
            </PopoverTrigger>
            <PopoverContent className="flex w-72 flex-col gap-2 p-3">
              <Input
                aria-label="Powód (opcjonalnie)"
                placeholder="Powód (opcjonalnie)"
                maxLength={500}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
              <Button
                size="sm"
                variant="outline"
                disabled={run.isPending}
                onClick={() =>
                  send(`Zamknięto jako „${lostStageName}”`, { action: "close", lost_reason: reason.trim() || undefined })
                }
              >
                Zamknij {opportunities(ids.length)}
              </Button>
            </PopoverContent>
          </Popover>
        )}
        <Button size="sm" variant="ghost" className="ml-auto" onClick={onClear} disabled={run.isPending}>
          Odznacz
        </Button>
      </div>
      {skipped.length > 0 && (
        <ul aria-label="Pominięte szanse" className="space-y-0.5 text-xs text-muted-foreground">
          {skipped.map((skip) => (
            <li key={skip.id}>
              Pominięta: {skip.title ?? `szansa ${skip.id}`} ({skip.reason})
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
