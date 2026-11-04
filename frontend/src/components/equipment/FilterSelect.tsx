"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const ALL = "__all__";

interface FilterSelectProps<T extends string> {
  label: string;
  value: T | "";
  options: { value: T; label: string }[];
  allLabel: string;
  onChange: (value: T | "") => void;
  className?: string;
}

/** Lista wyboru filtra z pozycją „wszystkie” (Radix nie przyjmuje pustej wartości). */
export function FilterSelect<T extends string>({
  label,
  value,
  options,
  allLabel,
  onChange,
  className,
}: FilterSelectProps<T>) {
  return (
    <Select
      value={value === "" ? ALL : value}
      onValueChange={(next) => onChange(next === ALL ? "" : (next as T))}
    >
      {/* Szerokość z treści (bez łamania „Wszystkie kategorie” na dwie linie). */}
      <SelectTrigger
        aria-label={label}
        className={className ?? "h-9 w-auto min-w-44 max-w-64 gap-2 whitespace-nowrap"}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{allLabel}</SelectItem>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
