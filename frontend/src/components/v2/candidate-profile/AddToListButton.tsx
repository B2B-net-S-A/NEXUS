"use client";

/**
 * „Na listę” w nagłówku profilu kandydata (prośba Olafa, 25.10.2026):
 * zaznaczasz, na których swoich listach ma być osoba, albo od razu zakładasz
 * nową („Tylko ja”). Listy żyją w panelu „Moi ludzie” → „Listy”.
 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, ListPlus, Lock, Plus, Users } from "lucide-react";

import {
  TALENT_POOLS_PREFIX,
  candidateListsApi,
  useCandidateLists,
  useListsForCandidate,
} from "@/lib/api/candidateLists";
import { apiErrorMessage } from "@/lib/api-error";
import { useAuthStore } from "@/store/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useToast } from "@/components/Toast";
import { cn } from "@/lib/utils";

interface AddToListButtonProps {
  candidateId: number;
}

export function AddToListButton({ candidateId }: AddToListButtonProps) {
  const me = useAuthStore((s) => s.user);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const queryClient = useQueryClient();
  const { showError } = useToast();
  // Licznik na przycisku liczy się od razu — bez otwierania okienka.
  const lists = useCandidateLists(me?.id);
  const memberOf = useListsForCandidate(candidateId);
  const mine = lists.data?.mine ?? [];
  const onIds = new Set(memberOf.data ?? []);
  const mineIds = new Set(mine.map((l) => l.id));
  const onMyLists = lists.data
    ? [...onIds].filter((id) => mineIds.has(id)).length
    : null;

  const refresh = () => queryClient.invalidateQueries({ queryKey: TALENT_POOLS_PREFIX });
  const toggle = useMutation({
    mutationFn: ({ listId, isOn }: { listId: number; isOn: boolean }) =>
      isOn
        ? candidateListsApi.remove(listId, candidateId)
        : candidateListsApi.add(listId, candidateId),
    onSuccess: refresh,
    onError: (err) => showError(apiErrorMessage(err, "Nie udało się zmienić listy.")),
  });
  const create = useMutation({
    mutationFn: async (listName: string) => {
      const list = await candidateListsApi.create(listName);
      await candidateListsApi.add(list.id, candidateId);
    },
    onSuccess: () => {
      setName("");
      void refresh();
    },
    onError: (err) => showError(apiErrorMessage(err, "Nie udało się utworzyć listy.")),
  });

  const label =
    onMyLists != null && onMyLists > 0
      ? `Na listach: ${onMyLists}`
      : "Na listę";

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button size="sm" variant="outline" className="min-h-11 min-w-11">
          <ListPlus className="h-4 w-4" />
          {label}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-2">
        <p className="px-2 pb-1 pt-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Moje listy
        </p>
        {lists.isError || memberOf.isError ? (
          <p role="alert" className="px-2 py-3 text-xs text-destructive">
            {apiErrorMessage(lists.error ?? memberOf.error, "Nie udało się wczytać list.")}
          </p>
        ) : !lists.isSuccess || !memberOf.isSuccess ? (
          <p className="px-2 py-3 text-xs text-muted-foreground">Wczytuję listy…</p>
        ) : mine.length === 0 ? (
          <p className="px-2 py-3 text-xs text-muted-foreground">
            Nie masz jeszcze listy. Wpisz nazwę poniżej — osoba trafi na nią od razu.
          </p>
        ) : (
          <ul className="max-h-64 space-y-0.5 overflow-y-auto">
            {mine.map((l) => {
              const isOn = onIds.has(l.id);
              return (
                <li key={l.id}>
                  <button
                    type="button"
                    onClick={() => toggle.mutate({ listId: l.id, isOn })}
                    disabled={toggle.isPending}
                    aria-pressed={isOn}
                    className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted disabled:opacity-60"
                  >
                    <span
                      className={cn(
                        "flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                        isOn ? "border-primary bg-primary text-primary-foreground" : "border-border",
                      )}
                      aria-hidden
                    >
                      {isOn ? <Check className="h-3 w-3" /> : null}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{l.name}</span>
                    <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
                      {l.team_visible ? (
                        <Users className="h-3 w-3" aria-label="Widzi zespół" />
                      ) : (
                        <Lock className="h-3 w-3" aria-label="Tylko ja" />
                      )}
                      {l.candidate_count}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        <form
          className="mt-2 flex gap-1.5 border-t border-border px-1 pt-2"
          onSubmit={(e) => {
            e.preventDefault();
            const trimmed = name.trim();
            if (trimmed) create.mutate(trimmed);
          }}
        >
          <Input
            value={name}
            maxLength={255}
            onChange={(e) => setName(e.target.value)}
            placeholder="Nowa lista…"
            aria-label="Nazwa nowej listy"
            className="h-8"
          />
          <Button
            type="submit"
            size="sm"
            variant="ghost"
            aria-label="Utwórz listę i dodaj osobę"
            loading={create.isPending}
            disabled={!name.trim()}
          >
            <Plus className="h-4 w-4" />
          </Button>
        </form>
      </PopoverContent>
    </Popover>
  );
}
