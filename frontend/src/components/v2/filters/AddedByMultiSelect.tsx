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

interface UserLite {
 id: number;
 name: string;
 role: string;
 is_active: boolean;
}

interface AddedByMultiSelectProps {
 value: number[]; // sentinel 0 ="System import" (created_by IS NULL)
 onChange: (ids: number[]) => void;
}

const SYSTEM_SENTINEL = 0;

export function AddedByMultiSelect({ value, onChange }: AddedByMultiSelectProps) {
 const [open, setOpen] = useState(false);
 const { data } = useQuery<UserLite[]>({
 queryKey: ["users-lite"],
 queryFn: () => api.get("/api/admin/users/lite").then((r) => r.data),
 staleTime: 60_000,
 });
 const users = (data ?? []).filter((u) => u.is_active);
 const selected = new Set(value);

 const toggle = (id: number) => {
 const next = new Set(selected);
 if (next.has(id)) next.delete(id);
 else next.add(id);
 onChange(Array.from(next));
 };

 const systemSelected = selected.has(SYSTEM_SENTINEL);
 const pickedUser = value.find((v) => v !== SYSTEM_SENTINEL);
 const label =
 value.length === 0
 ?"Wszyscy dodający"
 : value.length === 1
 ? systemSelected
 ?"Import systemowy"
 : (users.find((u) => u.id === pickedUser)?.name ?? `#${pickedUser}`)
 : `${value.length} osób`;

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
 <UserCircle className="h-4 w-4" /> {label}
 </span>
 <ChevronDown className="h-4 w-4 opacity-60" />
 </Button>
 </PopoverTrigger>
 <PopoverContent align="start" className="w-72 p-0">
 <Command>
 <CommandInput placeholder="Szukaj rekrutera…" />
 <CommandList>
 <CommandGroup heading="Specjalne">
 <CommandItem
 value="system-import"
 onSelect={() => toggle(SYSTEM_SENTINEL)}
 >
 <Check
 className={cn("mr-2 h-4 w-4",
 systemSelected ?"opacity-100" :"opacity-0"
 )}
 />
 <span>Import systemowy</span>
 </CommandItem>
 </CommandGroup>
 <CommandSeparator />
 <CommandGroup heading="Użytkownicy">
 <CommandEmpty>Brak użytkowników.</CommandEmpty>
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
 isSelected ?"opacity-100" :"opacity-0"
 )}
 />
 <span className="flex-1 truncate">{u.name}</span>
 <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
 {u.role}
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
