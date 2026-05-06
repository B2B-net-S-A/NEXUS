"use client";

import { useMemo, useState } from"react";
import { Check, ChevronDown } from"lucide-react";
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

export interface MultiSelectFilterOption<V extends string | number> {
 value: V;
 label: string;
}

export interface MultiSelectFilterProps<V extends string | number> {
 value: V[];
 onChange: (next: V[]) => void;
 options: ReadonlyArray<MultiSelectFilterOption<V>>;
 placeholder: string;
 searchPlaceholder?: string;
 /**
 * Returns trigger label given current count.
 * Default: count === 1 → option label; count > 1 → `${count} wybrane`.
 */
 triggerLabel?: (count: number, selected: V[]) => string;
 /** Tailwind width class for trigger; defaults to `w-[180px]`. */
 triggerWidthClass?: string;
 /** Show"Zaznacz wszystkie / Wyczyść" footer (default true). */
 showSelectAllClear?: boolean;
 /** Optional title attribute on trigger. */
 title?: string;
 /** Optional className appended to trigger. */
 className?: string;
}

const DEFAULT_TRIGGER_WIDTH ="w-[180px]";

export function MultiSelectFilter<V extends string | number>({
 value,
 onChange,
 options,
 placeholder,
 searchPlaceholder,
 triggerLabel,
 triggerWidthClass = DEFAULT_TRIGGER_WIDTH,
 showSelectAllClear = true,
 title,
 className,
}: MultiSelectFilterProps<V>) {
 const [open, setOpen] = useState(false);
 const selected = useMemo(() => new Set(value), [value]);

 const toggle = (v: V) => {
 const next = new Set(selected);
 if (next.has(v)) next.delete(v);
 else next.add(v);
 onChange(Array.from(next) as V[]);
 };

 const selectAll = () => onChange(options.map((o) => o.value));
 const clear = () => onChange([]);

 const label = (() => {
 if (value.length === 0) return placeholder;
 if (triggerLabel) return triggerLabel(value.length, value);
 if (value.length === 1) {
 const opt = options.find((o) => o.value === value[0]);
 return opt?.label ?? String(value[0]);
 }
 return `${value.length} wybrane`;
 })();

 return (
 <Popover open={open} onOpenChange={setOpen}>
 <PopoverTrigger asChild>
 <Button
 size="md"
 variant="outline"
 className={cn("justify-between", triggerWidthClass, className)}
 aria-expanded={open}
 title={title}
 >
 <span className="flex items-center gap-2 truncate">{label}</span>
 <ChevronDown className="h-4 w-4 opacity-60 flex-shrink-0" />
 </Button>
 </PopoverTrigger>
 <PopoverContent align="start" className="w-64 p-0">
 <Command>
 <CommandInput placeholder={searchPlaceholder ??"Szukaj…"} />
 <CommandList>
 <CommandEmpty>Brak opcji.</CommandEmpty>
 <CommandGroup>
 {options.map((opt) => {
 const isSelected = selected.has(opt.value);
 return (
 <CommandItem
 key={String(opt.value)}
 value={opt.label}
 onSelect={() => toggle(opt.value)}
 >
 <Check
 className={cn("mr-2 h-4 w-4",
 isSelected ?"opacity-100" :"opacity-0",
 )}
 />
 <span className="flex-1 truncate">{opt.label}</span>
 </CommandItem>
 );
 })}
 </CommandGroup>
 {showSelectAllClear && options.length > 1 && (
 <>
 <CommandSeparator />
 <div className="flex items-center justify-between px-2 py-1.5 text-xs">
 <button
 type="button"
 onClick={selectAll}
 className="text-muted-foreground hover:text-[hsl(var(--text))] hover:underline"
 >
 Zaznacz wszystkie
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
