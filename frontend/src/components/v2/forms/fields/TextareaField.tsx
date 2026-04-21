"use client";

import * as React from "react";
import { useFormContext } from "react-hook-form";
import { Textarea, type TextareaProps } from "@/components/ui/textarea";

interface Props extends Omit<TextareaProps, "name"> {
  name: string;
}

export function TextareaField({ name, ...rest }: Props) {
  const { register, formState } = useFormContext();
  const error = name.split(".").reduce<any>(
    (acc, key) => (acc ? acc[key] : undefined),
    formState.errors
  );
  return <Textarea id={name} invalid={!!error} {...register(name)} {...rest} />;
}
