"use client";

/**
 * Pola arkusza zapisywane do profilu osoby (08.11.2026): okres wypowiedzenia,
 * dni w biurze i tryb pracy. Widoczne tylko, gdy serwer podał `profile_fields`
 * (flaga rejestru faktów z rozmów).
 */

import type { UseFormReturn } from "react-hook-form";

import type { ScreeningFullFormValues } from "@/lib/screening-form";

const SET = { shouldDirty: true } as const;
const FIELD =
  "h-8 w-full rounded-md border border-border bg-background px-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring";

export function ScreeningProfileFields({
  methods,
  disabled,
}: {
  methods: UseFormReturn<ScreeningFullFormValues>;
  disabled: boolean;
}) {
  const values = methods.watch("profile");
  if (!values) return null;
  const update = (patch: Partial<NonNullable<ScreeningFullFormValues["profile"]>>) =>
    methods.setValue("profile", { ...values, ...patch }, SET);
  return (
    <div className="space-y-2 rounded-lg border border-border bg-background/40 p-3" data-testid="screening-profile-fields">
      <p className="text-xs font-medium text-foreground">Zapisze się w profilu osoby</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="min-w-0 space-y-1 text-xs text-muted-foreground">
          Okres wypowiedzenia
          <span className="flex gap-1.5">
            <input
              type="number"
              min={0}
              max={365}
              inputMode="numeric"
              disabled={disabled}
              value={values.notice_period}
              onChange={(event) => update({ notice_period: event.target.value })}
              className={FIELD}
              aria-label="Okres wypowiedzenia, liczba"
            />
            <select
              disabled={disabled}
              value={values.notice_period_unit}
              onChange={(event) =>
                update({ notice_period_unit: event.target.value as "days" | "weeks" | "months" })
              }
              className={FIELD}
              aria-label="Okres wypowiedzenia, jednostka"
            >
              <option value="days">dni</option>
              <option value="weeks">tyg.</option>
              <option value="months">mies.</option>
            </select>
          </span>
        </label>
        <label className="min-w-0 space-y-1 text-xs text-muted-foreground">
          Dni w biurze (tydzień)
          <input
            type="number"
            min={0}
            max={7}
            inputMode="numeric"
            disabled={disabled}
            value={values.max_onsite_days}
            onChange={(event) => update({ max_onsite_days: event.target.value })}
            className={FIELD}
          />
        </label>
        <label className="min-w-0 space-y-1 text-xs text-muted-foreground">
          Tryb pracy
          <select
            disabled={disabled}
            value={values.work_mode}
            onChange={(event) =>
              update({ work_mode: event.target.value as "" | "remote" | "hybrid" | "onsite" })
            }
            className={FIELD}
          >
            <option value="">nie wiadomo</option>
            <option value="remote">zdalnie</option>
            <option value="hybrid">hybrydowo</option>
            <option value="onsite">stacjonarnie</option>
          </select>
        </label>
      </div>
    </div>
  );
}
