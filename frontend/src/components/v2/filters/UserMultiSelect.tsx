"use client";

import { useState } from"react";
import { useQuery } from"@tanstack/react-query";
import { Check, ChevronDown, UserCircle } from"lucide-react";
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
 CommandSeparator,
} from"@/components/ui/command";

interface UserBrief {
 id: number;
 name: string;
 email?: string | null;
 role?: string | null;
}

interface UserMultiSelectProps {
 value: number[];
 onChange: (ids: number[]) => void;
 placeholder?: string;
 searchPlaceholder?: string;
 /** Tailwind width class for trigger; defaults to `w-[220px]`. */
 triggerWidthClass?: string;
}

const DEFAULT_TRIGGER_WIDTH ="w-[220px]";

/**
 * Multi-select picker for users (typically recruiters/owners).
 * Fetches `/api/users` (ownership-eligible roles only — excludes read-only viewers).
 * Distinct from `AddedByMultiSelect` which adds a sentinel"system import"
 * option (created_by IS NULL) on top of the same `/api/users` source.
 */
export function UserMultiSelect({
 value,
 onChange,
 placeholder ="Dowolny rekruter",
 searchPlaceholder ="Szukaj rekrutera…",
 triggerWidthClass = DEFAULT_TRIGGER_WIDTH,
}: UserMultiSelectProps) {
 const [open, setOpen] = useState(false);
 const { data } = useQuery<UserBrief[]>({
 queryKey: ["users-directory"],
 queryFn: () => api.get("/api/users").then((r) => r.data),
 staleTime: 60_000,
 });
 const users = data ?? [];
 const selected = new Set(value);

 const toggle = (id: number) => {
 const next = new Set(selected);
 if (next.has(id)) next.delete(id);
 else next.add(id);
 onChange(Array.from(next));
 };

 const selectAll = () => onChange(users.map((u) => u.id));
 const clear = () => onChange([]);

 const label = (() => {
 if (value.length === 0) return placeholder;
 if (value.length === 1) {
 return users.find((u) => u.id === value[0])?.name ?? `#${value[0]}`;
 }
 return `${value.length} osób`;
 })();

 return (
 <Popover open={open} onOpenChange={setOpen}>
 <PopoverTrigger asChild>
 <Button
 size="md"
 variant="outline"
 className={cn("justify-between", triggerWidthClass)}
 aria-expanded={open}
 >
 <span className="flex items-center gap-2 truncate">
 <UserCircle className="h-4 w-4" /> {label}
 </span>
 <ChevronDown className="h-4 w-4 opacity-60 shrink-0" />
 </Button>
 </PopoverTrigger>
 <PopoverContent align="start" className="w-72 p-0">
 <Command>
 <CommandInput placeholder={searchPlaceholder} />
 <CommandList>
 <CommandEmpty>Brak użytkowników.</CommandEmpty>
 <CommandGroup>
 {users.map((u) => {
 const isSelected = selected.has(u.id);
 return (
 <CommandItem
 key={u.id}
 value={u.name}
 onSelect={() => toggle(u.id)}
 >
 <Check
 className={cn("mr-2 h-4 w-4",
 isSelected ?"opacity-100" :"opacity-0",
 )}
 />
 <span className="flex-1 truncate">{u.name}</span>
 {u.role && (
 <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
 {u.role}
 </span>
 )}
 </CommandItem>
 );
 })}
 </CommandGroup>
 {users.length > 1 && (
 <>
 <CommandSeparator />
 <div className="flex items-center justify-between px-2 py-1.5 text-xs">
 <button
 type="button"
 onClick={selectAll}
 className="text-muted-foreground hover:text-[hsl(var(--text))] hover:underline"
 >
 Zaznacz wszystkich
 </button>
 <button
 type="button"
 onClick={clear}
 className="text-muted-foreground hover:text-[hsl(var(--text))] hover:underline disabled:opacity-50"
 disabled={value.length === 0}
 >
 Wyczyść
 </button>
 </div>
 </>
 )}
 </CommandList>
 </Command>
 </PopoverContent>
 </Popover>
 );
}
