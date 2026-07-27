"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Building2, Check, ChevronDown } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";

interface Client {
  id: number;
  name: string;
}

interface ClientMultiSelectProps {
  value: number[];
  onChange: (ids: number[]) => void;
}

export function ClientMultiSelect({ value, onChange }: ClientMultiSelectProps) {
  const [open, setOpen] = useState(false);
  // `/api/clients-lookup` returns ALL clients (id, name) — the paginated
  // `/api/clients?page_size=100` silently dropped clients past the first 100
  // (159 total), so a recruiter couldn't pick many of them.
  const { data } = useQuery<Client[]>({
    queryKey: ["clients-lookup"],
    queryFn: () => api.get("/api/clients-lookup").then((r) => r.data),
    staleTime: 60_000,
  });
  const clients = data ?? [];
  const selected = new Set(value);

  const toggle = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange(Array.from(next));
  };

  const label =
    value.length === 0
      ? "Dowolny klient"
      : value.length === 1
        ? (clients.find((c) => c.id === value[0])?.name ?? `#${value[0]}`)
        : `${value.length} klientów`;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          size="md"
          variant="outline"
          className="justify-between w-full"
          aria-expanded={open}
        >
          <span className="flex items-center gap-2 truncate">
            <Building2 className="h-4 w-4" /> {label}
          </span>
          <ChevronDown className="h-4 w-4 opacity-60 shrink-0" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64 p-0">
        <Command>
          <CommandInput placeholder="Szukaj klienta…" />
          <CommandList>
            <CommandEmpty>Brak klientów.</CommandEmpty>
            <CommandGroup>
              {clients.map((client) => {
                const isSelected = selected.has(client.id);
                return (
                  <CommandItem
                    key={client.id}
                    value={client.name}
                    onSelect={() => toggle(client.id)}
                  >
                    <Check
                      className={cn(
                        "mr-2 h-4 w-4",
                        isSelected ? "opacity-100" : "opacity-0"
                      )}
                    />
                    <span className="flex-1 truncate">{client.name}</span>
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
