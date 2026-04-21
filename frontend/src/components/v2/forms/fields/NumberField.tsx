"use client";

import * as React from "react";
import { useFormContext } from "react-hook-form";
import { Input, type InputProps } from "@/components/ui/input";

interface Props extends Omit<InputProps, "name" | "type"> {
  name: string;
  min?: number;
  max?: number;
  step?: number;
}

export function NumberField({ name, ...rest }: Props) {
  const { register, formState } = useFormContext();
  const error = name.split(".").reduce<any>(
    (acc, key) => (acc ? acc[key] : undefined),
    formState.errors
  );
  return (
    <Input
      id={name}
      type="number"
      invalid={!!error}
      {...register(name, { valueAsNumber: true })}
      {...rest}
    />
  );
}
