"use client";

/**
 * Wybór JEDNEGO klienta — trzon współdzielony przez Talent Radar i generator CV.
 *
 * Świadomie NIE jest to `ContractsClientPicker`: tamten ma wymuszoną pozycję
 * „Wszyscy klienci (lista globalna)" i efekt kanonizacji wołający `onChange`
 * z zewnątrz. Oba są sensowne w filtrze listy kontraktów i oba są szkodliwe
 * tam, gdzie klient steruje ZACHOWANIEM (dopuszczalność kandydata w radarze,
 * nazwa pliku i język w generatorze).
 *
 * Różnica między konsumentami sprowadza się do `allowClear`:
 *
 * * radar — klient jest WARUNKIEM operacji, odznaczyć się nie da;
 * * generator CV — klient jest opcjonalny (CV powstają też poza konkretnym
 *   zleceniem), więc wyczyszczenie musi być możliwe, a wymuszony wybór
 *   zamieniłby brak wiedzy w zgadywanie.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Building2, Check, ChevronsUpDown, X } from "lucide-react";

import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { filterClients, type ClientRef } from "@/lib/contract-client-filter";

export type { ClientRef };

interface Props {
  value: ClientRef | null;
  onChange: (client: ClientRef | null) => void;
  /** Klucz cache react-query — osobny per konsument, żeby jeden ekran nie
   * unieważniał listy drugiemu. */
  queryKey: string;
  placeholder?: string;
  /** Czy wolno wrócić do stanu „nie wybrano". */
  allowClear?: boolean;
  disabled?: boolean;
}

export function ClientSinglePicker({
  value,
  onChange,
  queryKey,
  placeholder = "Wybierz klienta…",
  allowClear = false,
  disabled = false,
}: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const clientsQuery = useQuery({
    queryKey: [queryKey],
    queryFn: async () =>
      (await api.get<ClientRef[]>("/api/clients-lookup")).data,
    staleTime: 5 * 60 * 1000,
  });

  const filtered = useMemo(
    () => filterClients(clientsQuery.data ?? [], query),
    [clientsQuery.data, query],
  );

  return (
    <div className="flex items-center gap-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            disabled={disabled}
            className="w-full justify-between font-normal"
          >
            <span className="flex items-center gap-2 truncate">
              <Building2
                className={cn(
                  "h-4 w-4 shrink-0",
                  value ? "text-primary" : "opacity-50",
                )}
              />
              <span
                className={cn("truncate", !value && "text-muted-foreground")}
              >
                {value ? value.name : placeholder}
              </span>
            </span>
            <ChevronsUpDown className="h-4 w-4 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-[320px] p-0">
          <Command shouldFilter={false}>
            <CommandInput
              placeholder="Szukaj klienta…"
              value={query}
              onValueChange={setQuery}
            />
            <CommandList>
              {clientsQuery.isLoading ? (
                <div className="p-3 text-sm text-muted-foreground">
                  Ładowanie…
                </div>
              ) : clientsQuery.isError ? (
                // Awaria pobrania NIE może wyglądać jak pusta lista — „Brak
                // wyników" czyta się jako „ta organizacja nie ma klientów",
                // czyli jako utrata danych, a nie jako nieudane sprawdzenie.
                <div className="flex flex-col gap-2 p-3">
                  <p className="text-sm text-destructive">
                    Nie udało się załadować listy klientów.
                  </p>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => clientsQuery.refetch()}
                  >
                    Spróbuj ponownie
                  </Button>
                </div>
              ) : (
                <CommandEmpty>Brak wyników.</CommandEmpty>
              )}
              <CommandGroup>
                {filtered.map((client) => (
                  <CommandItem
                    key={client.id}
                    value={String(client.id)}
                    onSelect={() => {
                      onChange(client);
                      setOpen(false);
                    }}
                  >
                    <Check
                      className={cn(
                        "mr-2 h-4 w-4",
                        value?.id === client.id ? "opacity-100" : "opacity-0",
                      )}
                    />
                    <span className="truncate">{client.name}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      {allowClear && value ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label="Wyczyść klienta"
          onClick={() => onChange(null)}
        >
          <X className="h-4 w-4" />
        </Button>
      ) : null}
    </div>
  );
}
