"use client";

/**
 * Wybór klienta dla radaru — bez opcji „wszyscy klienci".
 *
 * `ContractsClientPicker` wygląda na gotowca do ponownego użycia, ale ma stan
 * pusty podpisany „Wszyscy klienci (lista globalna)" i oferuje go jako
 * pozycję do wyboru. W kontraktach to sensowne — tam brak klienta znaczy „bez
 * filtra". Tutaj brak klienta znaczy „nie wolno szukać": filtr dopuszczalności
 * sprawdza względem niego blacklistę, NDA, konflikty konkurencyjne i weto
 * hiring managera, a backend odrzuca żądanie bez `client_id`.
 *
 * Zaproszenie użytkownika do wyboru, który z definicji nie może zadziałać, jest
 * gorsze niż brak podpowiedzi: przycisk zostaje wyszarzony, a człowiek widzi
 * zaznaczoną opcję i nie wie, czego jeszcze od niego chcemy.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Building2, Check, ChevronsUpDown } from "lucide-react";

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
  onChange: (client: ClientRef) => void;
}

export function TalentRadarClientPicker({ value, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const clientsQuery = useQuery({
    queryKey: ["clients-lookup-talent-radar"],
    queryFn: async () =>
      (await api.get<ClientRef[]>("/api/clients-lookup")).data,
    staleTime: 5 * 60 * 1000,
  });

  const filtered = useMemo(
    () => filterClients(clientsQuery.data ?? [], query),
    [clientsQuery.data, query],
  );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          className="w-full justify-between font-normal"
        >
          <span className="flex items-center gap-2 truncate">
            <Building2
              className={cn(
                "h-4 w-4 shrink-0",
                value ? "text-primary" : "opacity-50",
              )}
            />
            <span className={cn("truncate", !value && "text-muted-foreground")}>
              {value ? value.name : "Wybierz klienta…"}
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
              // Awaria pobrania NIE może wyglądać jak pusta lista. Bez tej
              // gałęzi `isError` przechodzi do `CommandEmpty` i użytkownik czyta
              // „Brak wyników", czyli „ta organizacja nie ma klientów" — zamiast
              // „nie udało się sprawdzić". To ta sama pomyłka, przed którą
              // ostrzega docstring workspace'u przy `meta.degraded`, tylko piętro
              // niżej: cisza po awarii jest nieodróżnialna od prawdziwego zera.
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
  );
}
