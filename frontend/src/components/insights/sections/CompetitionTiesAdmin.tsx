"use client";

/**
 * „Remis do rozstrzygnięcia" — admin ustala kolejność remisujących
 * w zamkniętym okresie konkursu płatnego.
 *
 * Remis, którego regulamin nie rozstrzyga, zamyka okres ze statusem
 * `tie_pending`: miejsca z remisu nie mają nagrody, dopóki ktoś nie zdecyduje.
 * Bez tego panelu decyzja nie miałaby gdzie zapaść, a nagroda wisiałaby
 * w próżni. Nic tu nie dzieje się jednym kliknięciem: kolejność ustawia się
 * w oknie, a zapis wymaga drugiego kroku z podsumowaniem, kto dostaje ile —
 * bez natywnego `window.confirm`.
 *
 * Bramka `isAdmin` oszczędza reszcie zespołu panelu, który i tak skończyłby
 * się 403 — zapis stoi na `AdminUser` po stronie serwera.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Scale } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  COMPETITION_LABELS,
  competitionTiesApi,
  competitionTiesQueryKeys,
  describeTieEntry,
  moveItem,
  type CompetitionTieEntry,
  type PendingCompetitionTie,
} from "@/lib/competition-ties-api";
import { useAuthStore } from "@/store/auth";

function orderedEntries(tie: PendingCompetitionTie): CompetitionTieEntry[][] {
  return tie.ties.map((group) => {
    const byId = new Map(group.entries.map((e) => [e.user_id, e]));
    return group.user_ids.map(
      (id) => byId.get(id) ?? { user_id: id, name: `#${id}`, metric_value: 0 },
    );
  });
}

function formatPrize(value: number | undefined): string {
  if (!value) return "bez nagrody";
  return `${value.toLocaleString("pl-PL")} zł`;
}

function TieDialog({
  tie,
  onClose,
}: {
  tie: PendingCompetitionTie;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [groups, setGroups] = useState(() => orderedEntries(tie));
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      competitionTiesApi.resolve(
        tie.competition_type,
        tie.period,
        groups.flatMap((group) => group.map((e) => e.user_id)),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: competitionTiesQueryKeys.pending(),
      });
      // Historia podium i rankingi czytają inne klucze.
      void queryClient.invalidateQueries({ queryKey: ["competitions"] });
      onClose();
    },
    onError: (err) =>
      setError(apiErrorMessage(err, "Nie udało się zapisać rozstrzygnięcia.")),
  });

  const label = COMPETITION_LABELS[tie.competition_type] ?? tie.competition_type;

  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open && !mutation.isPending) onClose();
      }}
      title={`Remis do rozstrzygnięcia — ${label}, ${tie.period}`}
      description={
        confirming
          ? "Sprawdź podział nagród. Po zapisie podium tego okresu jest niezmienne."
          : "Ustaw kolejność remisujących. Pierwsze osoby zajmą zablokowane miejsca."
      }
      size="md"
      footer={
        confirming ? (
          <>
            <Button
              variant="outline"
              onClick={() => setConfirming(false)}
              disabled={mutation.isPending}
            >
              Wróć do kolejności
            </Button>
            <Button
              onClick={() => {
                setError(null);
                mutation.mutate();
              }}
              loading={mutation.isPending}
            >
              Zatwierdź rozstrzygnięcie
            </Button>
          </>
        ) : (
          <>
            <Button variant="outline" onClick={onClose}>
              Anuluj
            </Button>
            <Button onClick={() => setConfirming(true)}>Dalej</Button>
          </>
        )
      }
    >
      <div className="space-y-4">
        {tie.ties.map((group, groupIdx) => (
          <section key={group.positions.join("-")} className="space-y-2">
            <h3 className="text-xs font-medium text-muted-foreground">
              Miejsca {group.positions.join(", ")}
            </h3>
            <ol className="divide-y divide-border/60 rounded-lg border border-border">
              {groups[groupIdx].map((entry, idx) => {
                const position = group.positions[idx];
                const prize = position
                  ? formatPrize(group.prizes_pln[String(position)])
                  : "bez miejsca na podium";
                return (
                  <li
                    key={entry.user_id}
                    className="flex items-center gap-2 px-3 py-2 text-sm"
                  >
                    <span className="w-16 shrink-0 text-xs text-muted-foreground">
                      {position ? `Miejsce ${position}` : "—"}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-foreground">
                        {entry.name}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {describeTieEntry(tie.competition_type, entry)}
                      </span>
                    </span>
                    <span className="shrink-0 text-xs font-medium text-foreground">
                      {prize}
                    </span>
                    {!confirming && (
                      <span className="flex shrink-0 gap-1">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Przesuń ${entry.name} wyżej`}
                          disabled={idx === 0}
                          onClick={() =>
                            setGroups((prev) =>
                              prev.map((g, i) =>
                                i === groupIdx ? moveItem(g, idx, -1) : g,
                              ),
                            )
                          }
                        >
                          <ArrowUp className="h-4 w-4" aria-hidden="true" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Przesuń ${entry.name} niżej`}
                          disabled={idx === groups[groupIdx].length - 1}
                          onClick={() =>
                            setGroups((prev) =>
                              prev.map((g, i) =>
                                i === groupIdx ? moveItem(g, idx, 1) : g,
                              ),
                            )
                          }
                        >
                          <ArrowDown className="h-4 w-4" aria-hidden="true" />
                        </Button>
                      </span>
                    )}
                  </li>
                );
              })}
            </ol>
          </section>
        ))}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
      </div>
    </AppModal>
  );
}

export function CompetitionTiesAdmin() {
  const user = useAuthStore((s) => s.user);
  const isAdmin =
    user?.role === "admin" || Boolean(user?.roles?.includes("admin"));
  const [active, setActive] = useState<PendingCompetitionTie | null>(null);

  const query = useQuery({
    queryKey: competitionTiesQueryKeys.pending(),
    queryFn: () => competitionTiesApi.pending(),
    enabled: isAdmin,
  });

  // Brak remisów to normalny stan świata — panel się nie pokazuje. Awaria
  // odczytu też go nie pokazuje: to informacja pomocnicza nad rankingiem,
  // a nie sekcja, której brak czyta się jak utratę danych.
  if (!isAdmin || !query.isSuccess || query.data.length === 0) return null;

  return (
    <div
      className="rounded-xl border border-warning/40 bg-warning-muted p-4"
      role="region"
      aria-label="Remis do rozstrzygnięcia"
    >
      <div className="flex items-center gap-2 text-sm font-medium text-warning-muted-foreground">
        <Scale className="h-4 w-4" aria-hidden="true" />
        Remis do rozstrzygnięcia
      </div>
      <p className="mt-1 text-xs text-warning-muted-foreground">
        Regulamin nie rozstrzyga kolejności — miejsca z remisu nie mają nagrody,
        dopóki nie ustalisz kolejności.
      </p>
      <ul className="mt-3 space-y-2">
        {query.data.map((tie) => (
          <li
            key={`${tie.competition_type}:${tie.period}`}
            className="flex flex-wrap items-center gap-2 text-sm"
          >
            <span className="text-foreground">
              {COMPETITION_LABELS[tie.competition_type] ?? tie.competition_type}
              {" · "}
              {tie.period}
            </span>
            <span className="text-xs text-muted-foreground">
              {tie.ties
                .map(
                  (g) =>
                    `miejsca ${g.positions.join(", ")}: ${g.user_ids.length} osoby`,
                )
                .join(" · ")}
            </span>
            <Button
              className="ml-auto"
              size="sm"
              variant="outline"
              onClick={() => setActive(tie)}
            >
              Rozstrzygnij
            </Button>
          </li>
        ))}
      </ul>
      {active && (
        <TieDialog
          key={`${active.competition_type}:${active.period}`}
          tie={active}
          onClose={() => setActive(null)}
        />
      )}
    </div>
  );
}
