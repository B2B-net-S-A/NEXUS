"use client";

import * as React from"react";
import { Star } from"lucide-react";
import { Controller, useFormContext } from"react-hook-form";
import { cn } from"@/lib/utils";

interface Props {
 name: string;
 max?: number;
 size?:"sm" |"md" |"lg";
}

export function RatingField({ name, max = 5, size ="md" }: Props) {
 const { control } = useFormContext();
 const sizeClass = size === "sm" ?"h-4 w-4" : size === "lg" ?"h-7 w-7" :"h-5 w-5";

 return (
 <Controller
 name={name}
 control={control}
 render={({ field }) => {
 const value = Number(field.value ?? 0);
 return (
 <div
 role="radiogroup"
 aria-label="Ocena"
 className="inline-flex items-center gap-1"
 >
 {Array.from({ length: max }, (_, i) => {
 const n = i + 1;
 const active = n <= value;
 return (
 <button
 key={n}
 type="button"
 role="radio"
 aria-checked={active}
 aria-label={`${n} z ${max}`}
 onClick={() => field.onChange(n)}
 className={cn("transition-colors focus:outline-none",
 active
 ?"text-amber-500"
 :"text-[hsl(var(--border))] hover:text-amber-300"
 )}
 >
 <Star
 className={cn(sizeClass, active ?"fill-amber-500" :"fill-transparent")}
 />
 </button>
 );
 })}
 {value > 0 && (
 <span className="ml-2 text-xs font-mono text-muted-foreground">
 {value}/{max}
 </span>
 )}
 </div>
 );
 }}
 />
 );
}
