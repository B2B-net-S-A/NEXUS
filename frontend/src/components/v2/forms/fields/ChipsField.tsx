"use client";

import * as React from"react";
import { X } from"lucide-react";
import { Controller, useFormContext } from"react-hook-form";
import { Input } from"@/components/ui/input";

interface Props {
 name: string;
 placeholder?: string;
 maxItems?: number;
}

/**
 * ChipsField – tag input for arrays. Also normalizes polymorphic inputs:
 * string → [string]
 * string[] → string[]
 * { name: string }[] → name[]
 * { technologies: string[] } → technologies
 * Handles Nexus's quirky `must_skills` shape without API layer changes.
 */
export function ChipsField({ name, placeholder, maxItems }: Props) {
 const { control } = useFormContext();
 const [input, setInput] = React.useState("");

 return (
 <Controller
 name={name}
 control={control}
 render={({ field }) => {
 const chips: string[] = normalize(field.value);
 const add = (raw: string) => {
 const v = raw.trim();
 if (!v || chips.includes(v)) return;
 if (maxItems && chips.length >= maxItems) return;
 field.onChange([...chips, v]);
 setInput("");
 };
 const remove = (v: string) => field.onChange(chips.filter((c) => c !== v));

 return (
 <div className="space-y-2">
 {chips.length > 0 && (
 <div className="flex flex-wrap gap-1.5">
 {chips.map((c) => (
 <span
 key={c}
 className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary"
 >
 {c}
 <button
 type="button"
 onClick={() => remove(c)}
 className="hover:opacity-70"
 aria-label={`Usuń ${c}`}
 >
 <X className="h-3 w-3" />
 </button>
 </span>
 ))}
 </div>
 )}
 <Input
 id={name}
 value={input}
 onChange={(e) => setInput(e.target.value)}
 onKeyDown={(e) => {
 if (e.key === "Enter" || e.key === ",") {
 e.preventDefault();
 add(input);
 } else if (e.key === "Backspace" && !input && chips.length) {
 remove(chips[chips.length - 1]);
 }
 }}
 placeholder={placeholder ??"Dodaj i naciśnij Enter"}
 />
 </div>
 );
 }}
 />
 );
}

export function normalize(raw: unknown): string[] {
 if (!raw) return [];
 if (typeof raw === "string") return raw ? [raw] : [];
 if (Array.isArray(raw)) {
 return raw
 .map((x) =>
 typeof x === "string" ? x : (x as any)?.name ?? (x as any)?.skill ?? null
 )
 .filter(Boolean) as string[];
 }
 if (typeof raw === "object" && raw !== null) {
 const r = raw as any;
 if (Array.isArray(r.technologies)) return r.technologies;
 if (Array.isArray(r.skills)) return normalize(r.skills);
 }
 return [];
}
