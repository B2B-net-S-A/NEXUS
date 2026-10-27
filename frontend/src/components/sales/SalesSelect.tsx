"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/** Wartość „bez wyboru” — Radix Select nie przyjmuje pustego napisu jako opcji. */
export const ANY = "__any__";

export interface SalesSelectOption {
  value: string;
  label: string;
}

interface SalesSelectProps {
  id?: string;
  value: string;
  onValueChange: (value: string) => void;
  options: readonly SalesSelectOption[];
  /** Etykieta pozycji „bez wyboru”; brak = pozycji nie ma. */
  anyLabel?: string;
  ariaLabel?: string;
  className?: string;
  disabled?: boolean;
}

/** Lista wyboru Sprzedaży: pusta wartość ↔ pozycja „bez wyboru”. */
export function SalesSelect({
  id,
  value,
  onValueChange,
  options,
  anyLabel,
  ariaLabel,
  className,
  disabled,
}: SalesSelectProps) {
  return (
    <Select
      value={value === "" ? ANY : value}
      onValueChange={(next) => onValueChange(next === ANY ? "" : next)}
      disabled={disabled}
    >
      <SelectTrigger id={id} aria-label={ariaLabel} className={className}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {anyLabel !== undefined && <SelectItem value={ANY}>{anyLabel}</SelectItem>}
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
