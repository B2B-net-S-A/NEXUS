"use client";

import * as React from"react";
import {
 FormProvider,
 useFormContext,
 type FieldValues,
 type UseFormReturn,
 type FieldPath,
 type SubmitHandler,
 Controller,
} from"react-hook-form";
import { AlertCircle } from"lucide-react";
import { cn } from"@/lib/utils";
import { Label } from"@/components/ui/label";

/**
 * v2 Forms — react-hook-form + zod wrapper.
 *
 * Usage:
 * const methods = useForm<FormValues>({ resolver: zodResolver(schema) });
 * <Form methods={methods} onSubmit={onSubmit}>
 * <FormField name="email" label="Email" required>
 * <TextField name="email" type="email" />
 * </FormField>
 * </Form>
 */

interface FormProps<T extends FieldValues>
 extends Omit<React.FormHTMLAttributes<HTMLFormElement>,"onSubmit"> {
 methods: UseFormReturn<T>;
 onSubmit: SubmitHandler<T>;
 children: React.ReactNode;
}

export function Form<T extends FieldValues>({
 methods,
 onSubmit,
 children,
 className,
 ...props
}: FormProps<T>) {
 return (
 <FormProvider {...methods}>
 <form
 onSubmit={methods.handleSubmit(onSubmit)}
 className={cn("space-y-4", className)}
 {...props}
 >
 {children}
 </form>
 </FormProvider>
 );
}

interface FormFieldProps {
 name: string;
 label?: React.ReactNode;
 description?: React.ReactNode;
 required?: boolean;
 className?: string;
 children: React.ReactNode;
}

/**
 * FormField — wraps a controlled field with label + error from RHF state.
 * Child field component reads `error` via useFieldError hook OR via being
 * inside useFormContext (Controller or register).
 */
export function FormField({
 name,
 label,
 description,
 required,
 className,
 children,
}: FormFieldProps) {
 const { formState } = useFormContext();
 const error = name.split(".").reduce<any>(
 (acc, key) => (acc ? acc[key] : undefined),
 formState.errors
 ) as { message?: string } | undefined;

 return (
 <div className={cn("flex flex-col gap-1.5", className)}>
 {label && (
 <Label htmlFor={name} required={required}>
 {label}
 </Label>
 )}
 {children}
 {description && !error && (
 <p className="text-xs text-muted-foreground">{description}</p>
 )}
 {error?.message && (
 <p
 role="alert"
 className="inline-flex items-center gap-1 text-xs font-medium text-primary"
 >
 <AlertCircle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
 <span>{error.message}</span>
 </p>
 )}
 </div>
 );
}

/**
 * Re-export Controller for component-heavy fields (Select, Chips, etc.)
 * that need a render prop pattern.
 */
export { Controller };

/**
 * Convenience: typed field path helper.
 */
export type FieldName<T extends FieldValues> = FieldPath<T>;
