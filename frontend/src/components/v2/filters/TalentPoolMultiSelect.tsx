"use client";

import { useState } from"react";
import { useQuery } from"@tanstack/react-query";
import { Check, ChevronDown, Users } from"lucide-react";
import api from"@/lib/api";
import { cn } from"@/lib/utils";
import { Button } from"@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from"@/components/ui/popover";
import {
 Command,
 CommandEmpty,
 CommandGroup,
 CommandInput,
 CommandItem,
 CommandList,
} from"@/components/ui/command";

interface TalentPool {
 id: number;
 name: string;
 candidate_count?: number;
}

interface TalentPoolMultiSelectProps {
 value: number[];
 onChange: (ids: number[]) => void;
}

export function TalentPoolMultiSelect({ value, onChange }: TalentPoolMultiSelectProps) {
 const [open, setOpen] = useState(false);
 const { data } = useQuery<TalentPool[]>({
 queryKey: ["talent-pools-lite"],
 queryFn: () => api.get("/api/talent-pools").then((r) => r.data),
 staleTime: 60_000,
 });
 const pools = data ?? [];
 const selected = new Set(value);

 const toggle = (id: number) => {
 const next = new Set(selected);
 if (next.has(id)) next.delete(id);
 else next.add(id);
 onChange(Array.from(next));
 };

 const label =
 value.length === 0
 ?"Wszystkie pule"
 : value.length === 1
 ? (pools.find((p) => p.id === value[0])?.name ?? `#${value[0]}`)
 : `${value.length} pul`;

 return (
 <Popover open={open} onOpenChange={setOpen}>
 <PopoverTrigger asChild>
 <Button
 size="md"
 variant="outline"
 className="justify-between w-full"
 aria-expanded={open}
 >
 <span className="flex items-center gap-2">
 <Users className="h-4 w-4" /> {label}
 </span>
 <ChevronDown className="h-4 w-4 opacity-60" />
 </Button>
 </PopoverTrigger>
 <PopoverContent align="start" className="w-64 p-0">
 <Command>
 <CommandInput placeholder="Szukaj puli…" />
 <CommandList>
 <CommandEmpty>Brak pul.</CommandEmpty>
 <CommandGroup>
 {pools.map((pool) => {
 const isSelected = selected.has(pool.id);
 return (
 <CommandItem
 key={pool.id}
 value={pool.name}
 onSelect={() => toggle(pool.id)}
 >
 <Check
 className={cn("mr-2 h-4 w-4",
 isSelected ?"opacity-100" :"opacity-0"
 )}
 />
 <span className="flex-1 truncate">{pool.name}</span>
 {pool.candidate_count !== undefined && (
 <span className="text-xs text-muted-foreground">
 {pool.candidate_count}
 </span>
 )}
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
