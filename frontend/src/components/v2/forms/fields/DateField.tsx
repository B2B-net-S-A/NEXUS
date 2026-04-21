"use client";

import * as React from "react";
import { useFormContext } from "react-hook-form";
import { Input, type InputProps } from "@/components/ui/input";

interface Props extends Omit<InputProps, "name" | "type"> {
  name: string;
}

export function DateField({ name, ...rest }: Props) {
  const { register, formState } = useFormContext();
  const error = name.split(".").reduce<any>(
    (acc, key) => (acc ? acc[key] : undefined),
    formState.errors
  );
  return (
    <Input id={name} type="date" invalid={!!error} {...register(name)} {...rest} />
  );
}
