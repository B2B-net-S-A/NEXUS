"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Briefcase, Check, ChevronDown } from "lucide-react";
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

interface Recruitment {
  id: number;
  title: string;
}

interface RecruitmentMultiSelectProps {
  value: number[];
  onChange: (ids: number[]) => void;
}

export function RecruitmentMultiSelect({
  value,
  onChange,
}: RecruitmentMultiSelectProps) {
  const [open, setOpen] = useState(false);
  // `/api/jobs-lookup` zwraca lekką listę (id, title) rekrutacji — bez ciężkiego
  // payloadu `/api/jobs` (klient, etapy, właściciele itd.). Spójne z tym jak
  // `ClientMultiSelect` używa `/api/clients-lookup`.
  const { data } = useQuery<Recruitment[]>({
    queryKey: ["jobs-lookup"],
    queryFn: () => api.get("/api/jobs-lookup").then((r) => r.data),
    staleTime: 60_000,
  });
  const recruitments = data ?? [];
  const selected = new Set(value);

  const toggle = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange(Array.from(next));
  };

  const label =
    value.length === 0
      ? "Dowolna rekrutacja"
      : value.length === 1
        ? (recruitments.find((r) => r.id === value[0])?.title ?? `#${value[0]}`)
        : `${value.length} rekrutacji`;

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
            <Briefcase className="h-4 w-4" /> {label}
          </span>
          <ChevronDown className="h-4 w-4 opacity-60 shrink-0" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 p-0">
        <Command>
          <CommandInput placeholder="Szukaj rekrutacji…" />
          <CommandList>
            <CommandEmpty>Brak rekrutacji.</CommandEmpty>
            <CommandGroup>
              {recruitments.map((recruitment) => {
                const isSelected = selected.has(recruitment.id);
                return (
                  <CommandItem
                    // Tytuły rekrutacji bywają zduplikowane (ten sam tytuł u 2
                    // klientów) — `#id` w `value` trzyma pozycje unikalne dla
                    // cmdk i pozwala szukać też po id.
                    key={recruitment.id}
                    value={`${recruitment.title} #${recruitment.id}`}
                    onSelect={() => toggle(recruitment.id)}
                  >
                    <Check
                      className={cn(
                        "mr-2 h-4 w-4",
                        isSelected ? "opacity-100" : "opacity-0"
                      )}
                    />
                    <span className="flex-1 truncate">{recruitment.title}</span>
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
