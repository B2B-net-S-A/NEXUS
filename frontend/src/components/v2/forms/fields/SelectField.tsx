"use client";

import * as React from "react";
import { Controller, useFormContext } from "react-hook-form";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface Option {
  value: string;
  label: string;
}

interface Props {
  name: string;
  options: Option[];
  placeholder?: string;
  disabled?: boolean;
}

export function SelectField({ name, options, placeholder, disabled }: Props) {
  const { control, formState } = useFormContext();
  const error = name.split(".").reduce<any>(
    (acc, key) => (acc ? acc[key] : undefined),
    formState.errors
  );
  return (
    <Controller
      name={name}
      control={control}
      render={({ field }) => (
        <Select
          value={field.value ?? ""}
          onValueChange={field.onChange}
          disabled={disabled}
        >
          <SelectTrigger id={name} invalid={!!error}>
            <SelectValue placeholder={placeholder ?? "Wybierz…"} />
          </SelectTrigger>
          <SelectContent>
            {options.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    />
  );
}
