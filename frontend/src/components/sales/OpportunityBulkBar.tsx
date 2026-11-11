"use client";

import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { api } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { useInvalidateSales, type Stage } from "@/lib/api/sales";

import { dueAtMorning, plusDays } from "./CallLogDialogs";
import { plural } from "./my-day";
import { SalesSelect } from "./SalesSelect";
import { useOwnerFilterOptions } from "./useOwnerFilterOptions";

const WHEN = [
  { label: "Jutro", days: 1 },
  { label: "Za 3 dni", days: 3 },
  { label: "Za tydzień", days: 7 },
] as const;

interface OpportunityBulkBarProps {
  ids: number[];
  lostStage: Stage | undefined;
  onClear: () => void;
}

/**
 * Makieta 11.11.2026: akcje dla wielu zaznaczonych szans naraz. W makiecie każda szansa
 * idzie osobnym zapytaniem do istniejących tras; wersja do wdrożenia dostanie jedną trasę
 * zbiorczą z `owner_tasks.hand_over` przy zmianie opiekuna.
 */
export function OpportunityBulkBar({ ids, lostStage, onClear }: OpportunityBulkBarProps) {
  const invalidate = useInvalidateSales();
  const { showError, showSuccess } = useToast();
  const owners = useOwnerFilterOptions(null).filter((option) => option.value.startsWith("acct:"));
  const [pending, setPending] = useState(false);
  const [owner, setOwner] = useState("");
  const [reason, setReason] = useState("");
  const count = plural(ids.length, "szansę", "szanse", "szans");

  const run = async (label: string, action: (id: number) => Promise<unknown>) => {
    setPending(true);
    try {
      for (const id of ids) await action(id);
      showSuccess(`${label}: ${count}.`);
      onClear();
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać wszystkich szans."));
    } finally {
      setPending(false);
      void invalidate();
    }
  };

  return (
    <div
      role="region"
      aria-label="Zaznaczone szanse"
      className="sticky top-0 z-20 flex flex-wrap items-center gap-2 rounded-lg border border-primary/40 bg-primary/5 px-3 py-2 text-sm"
    >
      <span className="font-medium text-foreground">Zaznaczone: {count}</span>
      <Popover>
        <PopoverTrigger asChild>
          <Button size="sm" variant="outline" disabled={pending}>
            Zaplanuj krok
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-2">
          <p className="mb-1 text-xs text-muted-foreground">Zadzwonić…</p>
          <div className="flex gap-1">
            {WHEN.map((option) => (
              <Button
                key={option.days}
                size="sm"
                variant="outline"
                className="h-7 px-2"
                onClick={() =>
                  void run(`Krok „Zadzwonić” ${option.label.toLowerCase()}`, (id) =>
                    api.post("/api/sales/activities", {
                      kind: "task",
                      subject: "Zadzwonić",
                      due_at: dueAtMorning(plusDays(option.days)),
                      opportunity_id: id,
                    }),
                  )
                }
              >
                {option.label}
              </Button>
            ))}
          </div>
        </PopoverContent>
      </Popover>
      <Popover>
        <PopoverTrigger asChild>
          <Button size="sm" variant="outline" disabled={pending}>
            Zmień opiekuna
          </Button>
        </PopoverTrigger>
        <PopoverContent className="flex w-72 flex-col gap-2 p-3">
          <SalesSelect ariaLabel="Nowy opiekun" value={owner} onValueChange={setOwner} options={owners} anyLabel="Wybierz osobę" />
          <Button
            size="sm"
            disabled={!owner}
            onClick={() =>
              void run("Zmieniono opiekuna", (id) =>
                api.patch(`/api/sales/opportunities/${id}`, { owner_user_id: Number(owner.slice(5)) }),
              )
            }
          >
            Przekaż {count}
          </Button>
        </PopoverContent>
      </Popover>
      {lostStage && (
        <Popover>
          <PopoverTrigger asChild>
            <Button size="sm" variant="outline" disabled={pending}>
              Zamknij z powodem
            </Button>
          </PopoverTrigger>
          <PopoverContent className="flex w-72 flex-col gap-2 p-3">
            <Input
              aria-label="Powód (opcjonalnie)"
              placeholder="Powód (opcjonalnie)"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                void run(`Zamknięto jako „${lostStage.name}”`, (id) =>
                  api.post(`/api/sales/opportunities/${id}/move`, {
                    stage_id: lostStage.id,
                    lost_reason: reason.trim() || undefined,
                  }),
                )
              }
            >
              Zamknij {count}
            </Button>
          </PopoverContent>
        </Popover>
      )}
      <Button size="sm" variant="ghost" className="ml-auto" onClick={onClear} disabled={pending}>
        Odznacz
      </Button>
    </div>
  );
}
