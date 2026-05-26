"use client";

import { useMemo, useState } from"react";
import { useQuery } from"@tanstack/react-query";
import { Check, ChevronDown, Users } from"lucide-react";
import api from"@/lib/api";
import { cn } from"@/lib/utils";
import { Button } from"@/components/ui/button";
import { Badge } from"@/components/ui/badge";
import { Popover, PopoverContent, PopoverTrigger } from"@/components/ui/popover";
import {
 Command,
 CommandEmpty,
 CommandGroup,
 CommandInput,
 CommandItem,
 CommandList,
 CommandSeparator,
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

 // Backend domyślnie sortuje po `created_at DESC`, więc świeżo utworzone puste
 // pule dominują nad starszymi populated. W filtrze dzielimy listę: najpierw
 // pule z kandydatami (po liczbie malejąco, potem alfabetycznie), poniżej
 // wizualnie wytłumione puste — żeby user nie wybierał np. "Java" (0 członków)
 // myśląc że to "Java Backend Senior" (3 członków).
 const { populated, empty } = useMemo(() => {
 const pop = pools.filter((p) => (p.candidate_count ?? 0) > 0);
 const emp = pools.filter((p) => (p.candidate_count ?? 0) === 0);
 pop.sort((a, b) =>
 (b.candidate_count ?? 0) - (a.candidate_count ?? 0) || a.name.localeCompare(b.name)
 );
 emp.sort((a, b) => a.name.localeCompare(b.name));
 return { populated: pop, empty: emp };
 }, [pools]);

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
 <PopoverContent align="start" className="w-72 p-0">
 <Command>
 <CommandInput placeholder="Szukaj puli…" />
 <CommandList>
 <CommandEmpty>Brak pul.</CommandEmpty>
 {populated.length > 0 && (
 <CommandGroup heading={`Z kandydatami (${populated.length})`}>
 {populated.map((pool) => {
 const isSelected = selected.has(pool.id);
 return (
 <CommandItem
 key={pool.id}
 value={pool.name}
 onSelect={() => toggle(pool.id)}
 >
 <Check
 className={cn(
 "mr-2 h-4 w-4",
 isSelected ?"opacity-100" :"opacity-0"
 )}
 />
 <span className="flex-1 truncate">{pool.name}</span>
 <Badge variant="soft" size="sm" className="ml-2">
 {pool.candidate_count ?? 0}
 </Badge>
 </CommandItem>
 );
 })}
 </CommandGroup>
 )}
 {empty.length > 0 && (
 <>
 {populated.length > 0 && <CommandSeparator />}
 <CommandGroup heading={`Bez kandydatów (${empty.length})`}>
 {empty.map((pool) => {
 const isSelected = selected.has(pool.id);
 return (
 <CommandItem
 key={pool.id}
 value={pool.name}
 onSelect={() => toggle(pool.id)}
 className={isSelected ? undefined :"opacity-60"}
 >
 <Check
 className={cn(
 "mr-2 h-4 w-4",
 isSelected ?"opacity-100" :"opacity-0"
 )}
 />
 <span className="flex-1 truncate">{pool.name}</span>
 <Badge variant="outline" size="sm" className="ml-2">
 0
 </Badge>
 </CommandItem>
 );
 })}
 </CommandGroup>
 </>
 )}
 </CommandList>
 </Command>
 </PopoverContent>
 </Popover>
 );
}
