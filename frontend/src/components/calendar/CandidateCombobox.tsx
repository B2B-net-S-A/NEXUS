"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronsUpDown, Search, X } from "lucide-react";

import { candidatesApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";

export interface CandidateChoice {
  id: number;
  label: string;
}

/**
 * Kandydat do wydarzenia: wyszukiwanie po stronie serwera, nie lista
 * „100 ostatnich". Zwykły `<select>` z `page_size: 100` pokazywał setną część
 * bazy bez szukania — starszej osoby nie dało się wskazać wcale (audyt B07).
 * Wyniesione z formularza „Nowe wydarzenie", bo tego samego wyboru potrzebuje
 * edycja wydarzenia.
 */
export function CandidateCombobox({
  value,
  onChange,
  labelledBy,
}: {
  value: CandidateChoice | null;
  onChange: (value: CandidateChoice | null) => void;
  /** `id` etykiety pola — nazwa dostępna comboboxa. */
  labelledBy: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const debouncedQuery = useDebouncedValue(query.trim(), 300);
  const candidatesQuery = useQuery({
    queryKey: ["calendar-candidate-search", debouncedQuery],
    queryFn: () =>
      candidatesApi
        .list({ q: debouncedQuery || undefined, page_size: 20 })
        .then(
          (r) =>
            (r.data?.items || []) as Array<{
              id: number;
              name?: string;
              lastname?: string;
              email?: string | null;
            }>,
        ),
    enabled: open,
  });

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          role="combobox"
          aria-expanded={open}
          aria-labelledby={labelledBy}
          className="w-full flex items-center justify-between gap-2 border border-border rounded-lg px-3 py-2 text-sm text-left focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
        >
          <span className="flex items-center gap-2 truncate">
            <Search className="h-4 w-4 shrink-0 opacity-60" />
            <span className={cn("truncate", !value && "text-muted-foreground")}>
              {value ? value.label : "Szukaj kandydata…"}
            </span>
          </span>
          <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-(--radix-popover-trigger-width) p-0">
        <Command shouldFilter={false}>
          <CommandInput
            placeholder="Szukaj kandydata…"
            value={query}
            onValueChange={setQuery}
          />
          <CommandList>
            {candidatesQuery.isLoading ? (
              <div className="p-3 text-sm text-muted-foreground">Szukam…</div>
            ) : candidatesQuery.isError ? (
              // Awaria ≠ „nikogo nie ma": pusta lista czytałaby się jak brak
              // kandydata w bazie.
              <div className="p-3 text-sm text-destructive" role="alert">
                Nie udało się wyszukać kandydatów.
              </div>
            ) : (
              <CommandEmpty>Brak wyników.</CommandEmpty>
            )}
            <CommandGroup>
              {value ? (
                <CommandItem
                  value="__none__"
                  onSelect={() => {
                    onChange(null);
                    setOpen(false);
                  }}
                >
                  <X className="mr-2 h-4 w-4" />
                  Bez kandydata
                </CommandItem>
              ) : null}
              {(candidatesQuery.data ?? []).map((c) => {
                const label =
                  `${c.name ?? ""} ${c.lastname ?? ""}`.trim() || `Kandydat #${c.id}`;
                return (
                  <CommandItem
                    key={c.id}
                    value={String(c.id)}
                    onSelect={() => {
                      onChange({ id: c.id, label });
                      setOpen(false);
                    }}
                  >
                    <Check
                      className={cn(
                        "mr-2 h-4 w-4",
                        value?.id === c.id ? "opacity-100" : "opacity-0",
                      )}
                    />
                    <span className="truncate">
                      {label}
                      {c.email ? (
                        <span className="ml-1 text-xs text-muted-foreground">{c.email}</span>
                      ) : null}
                    </span>
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
