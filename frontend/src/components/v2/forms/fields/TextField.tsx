"use client";

import * as React from "react";
import { useFormContext } from "react-hook-form";
import { Input, type InputProps } from "@/components/ui/input";

interface Props extends Omit<InputProps, "name"> {
  name: string;
}

export function TextField({ name, ...rest }: Props) {
  const { register, formState } = useFormContext();
  const error = name.split(".").reduce<any>(
    (acc, key) => (acc ? acc[key] : undefined),
    formState.errors
  );
  return <Input id={name} invalid={!!error} {...register(name)} {...rest} />;
}
