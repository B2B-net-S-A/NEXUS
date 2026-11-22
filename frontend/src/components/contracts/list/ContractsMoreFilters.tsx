"use client";
// „Więcej filtrów” listy kontraktów (przebudowa 20.11.2026, wariant A): status,
// typ umowy i daty w jednym okienku. Status nie stoi już w pasku obok pigułek,
// które mówią to samo („Status: 2” = pigułka „Aktywne”).
import { SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  CONTRACT_STATUS_OPTIONS,
  CONTRACT_TYPE_OPTIONS,
  type ContractStatusValue,
  type ContractTypeValue,
} from "@/lib/filter-options";
import { contractStatusLabel } from "@/lib/status-labels";

export interface ContractsDateRange {
  startFrom: string;
  startTo: string;
  orderEndFrom: string;
  orderEndTo: string;
}

export const EMPTY_DATE_RANGE: ContractsDateRange = {
  startFrom: "",
  startTo: "",
  orderEndFrom: "",
  orderEndTo: "",
};

export function rangeInverted(from: string, to: string): boolean {
  return Boolean(from && to && from > to);
}

function toggle<T>(values: readonly T[], value: T): T[] {
  return values.includes(value) ? values.filter((v) => v !== value) : [...values, value];
}

function DateRangeFields({
  legend,
  from,
  to,
  onChange,
}: {
  legend: string;
  from: string;
  to: string;
  onChange: (from: string, to: string) => void;
}) {
  const inverted = rangeInverted(from, to);
  return (
    <fieldset className="space-y-1.5">
      <legend className="text-xs font-semibold text-foreground">{legend}</legend>
      <div className="grid grid-cols-2 gap-2">
        <label className="space-y-1 text-[11px] text-muted-foreground">
          <span>Od</span>
          <Input type="date" value={from} aria-label={`${legend} od`} onChange={(e) => onChange(e.target.value, to)} />
        </label>
        <label className="space-y-1 text-[11px] text-muted-foreground">
          <span>Do</span>
          <Input type="date" value={to} aria-label={`${legend} do`} onChange={(e) => onChange(from, e.target.value)} />
        </label>
      </div>
      {inverted && (
        <p role="alert" className="text-[11px] text-destructive">
          Data „od" jest późniejsza niż „do" — popraw zakres, żeby go zastosować.
        </p>
      )}
    </fieldset>
  );
}

export interface ContractsMoreFiltersProps {
  statusFilter: ContractStatusValue[];
  onStatusChange: (next: ContractStatusValue[]) => void;
  typeFilter: ContractTypeValue[];
  onTypeChange: (next: ContractTypeValue[]) => void;
  dateRange: ContractsDateRange;
  onDateChange: (patch: Partial<ContractsDateRange>) => void;
  /** Ile filtrów z okienka działa — liczba na przycisku. */
  activeCount: number;
}

export function ContractsMoreFilters({
  statusFilter,
  onStatusChange,
  typeFilter,
  onTypeChange,
  dateRange,
  onDateChange,
  activeCount,
}: ContractsMoreFiltersProps) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          size="sm"
          variant="outline"
          className="gap-1.5"
          aria-label="Więcej filtrów: status, typ umowy, daty"
          title="Status, typ umowy, daty startu i końca zamówienia"
        >
          <SlidersHorizontal className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          Więcej filtrów
          {activeCount > 0 ? (
            <span className="rounded-full bg-primary px-1.5 text-[11px] font-semibold leading-5 tabular-nums text-primary-foreground">
              {activeCount}
            </span>
          ) : null}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 space-y-3">
        <fieldset className="space-y-1.5">
          <legend className="text-xs font-semibold text-foreground">Status umowy</legend>
          <p className="text-[11px] leading-4 text-muted-foreground">
            Zwykle wystarczą pigułki nad listą; tu można wybrać dowolny zestaw statusów.
          </p>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
            {CONTRACT_STATUS_OPTIONS.map((option) => (
              <label key={option.value} className="flex items-center gap-2 text-xs text-foreground">
                <Checkbox
                  checked={statusFilter.includes(option.value)}
                  onCheckedChange={() => onStatusChange(toggle(statusFilter, option.value))}
                  aria-label={`Status: ${contractStatusLabel(option.value)}`}
                />
                {contractStatusLabel(option.value)}
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset className="space-y-1.5">
          <legend className="text-xs font-semibold text-foreground">Typ umowy</legend>
          <div className="flex flex-wrap gap-x-3 gap-y-1.5">
            {CONTRACT_TYPE_OPTIONS.map((option) => (
              <label key={option.value} className="flex items-center gap-2 text-xs text-foreground">
                <Checkbox
                  checked={typeFilter.includes(option.value)}
                  onCheckedChange={() => onTypeChange(toggle(typeFilter, option.value))}
                  aria-label={`Typ: ${option.label}`}
                />
                {option.label}
              </label>
            ))}
          </div>
        </fieldset>
        <DateRangeFields
          legend="Data rozpoczęcia"
          from={dateRange.startFrom}
          to={dateRange.startTo}
          onChange={(from, to) => onDateChange({ startFrom: from, startTo: to })}
        />
        <DateRangeFields
          legend="Data zakończenia zamówienia"
          from={dateRange.orderEndFrom}
          to={dateRange.orderEndTo}
          onChange={(from, to) => onDateChange({ orderEndFrom: from, orderEndTo: to })}
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Zamówienia bezterminowe i kontrakty bez zamówienia nie mieszczą się w zakresie końca zamówienia.
        </p>
        <Button size="sm" variant="ghost" className="w-full" onClick={() => onDateChange(EMPTY_DATE_RANGE)}>
          Wyczyść daty
        </Button>
      </PopoverContent>
    </Popover>
  );
}
