"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Building2, Check, ChevronsUpDown, Users, X } from "lucide-react";
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
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { filterClients, type ClientRef } from "@/lib/contract-client-filter";

export type { ClientRef };

interface Props {
  value: ClientRef | null;
  onChange: (client: ClientRef | null) => void;
}

export function ContractsClientPicker({ value, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const clientsQuery = useQuery({
    queryKey: ["clients-lookup-contracts-picker"],
    queryFn: async () => (await api.get<ClientRef[]>("/api/clients-lookup")).data,
    staleTime: 5 * 60 * 1000,
  });

  const filtered = useMemo(
    () => filterClients(clientsQuery.data ?? [], query),
    [clientsQuery.data, query],
  );

  useEffect(() => {
    if (!value || !clientsQuery.data) return;
    const canonical = clientsQuery.data.find((client) => client.id === value.id);
    if (canonical && canonical.name !== value.name) onChange(canonical);
  }, [clientsQuery.data, onChange, value]);

  return (
    <div className="flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-2">
      <span className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground shrink-0">
        Klient
      </span>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            className="min-w-[260px] justify-between font-normal"
          >
            <span className="flex items-center gap-2 truncate">
              {value ? (
                <Building2 className="h-4 w-4 shrink-0 text-primary" />
              ) : (
                <Users className="h-4 w-4 shrink-0 opacity-60" />
              )}
              {value ? value.name : "Wszyscy klienci (lista globalna)"}
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
                <div className="p-3 text-sm text-muted-foreground">Ładowanie…</div>
              ) : (
                <CommandEmpty>Brak wyników.</CommandEmpty>
              )}
              <CommandGroup>
                <CommandItem
                  value="__all__"
                  onSelect={() => {
                    onChange(null);
                    setOpen(false);
                  }}
                >
                  <Check
                    className={cn(
                      "mr-2 h-4 w-4",
                      value === null ? "opacity-100" : "opacity-0",
                    )}
                  />
                  <Users className="mr-2 h-4 w-4 opacity-60" />
                  Wszyscy klienci (lista globalna)
                </CommandItem>
                {filtered.map((c) => (
                  <CommandItem
                    key={c.id}
                    value={String(c.id)}
                    onSelect={() => {
                      onChange(c);
                      setOpen(false);
                    }}
                  >
                    <Check
                      className={cn(
                        "mr-2 h-4 w-4",
                        value?.id === c.id ? "opacity-100" : "opacity-0",
                      )}
                    />
                    <span className="truncate">{c.name}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      {value && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => onChange(null)}
          className="text-muted-foreground"
        >
          <X className="h-4 w-4" /> Wyczyść
        </Button>
      )}
    </div>
  );
}
