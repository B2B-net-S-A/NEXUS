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
      <SelectTrigger aria-label={label} className={className ?? "h-9 w-44"}>
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
