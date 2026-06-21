import * as React from "react";
import { cn } from "@/lib/utils";
import { Label } from "@/components/ui/label";

interface FormSectionProps {
  /** Section heading shown above the field grid. */
  title?: string;
  /** Optional supporting copy rendered under the title. */
  description?: string;
  /** Number of columns on sm+ screens. Single column stacks everywhere. */
  columns?: 1 | 2;
  className?: string;
  children: React.ReactNode;
}

/**
 * FormSection — a titled, card-less grouping of form fields.
 * Renders an optional heading + description, then a responsive 1-2 column grid.
 */
export function FormSection({
  title,
  description,
  columns = 2,
  className,
  children,
}: FormSectionProps) {
  return (
    <section className={cn("flex flex-col gap-5", className)}>
      {(title || description) && (
        <div className="flex flex-col gap-1">
          {title && (
            <h3 className="text-sm font-semibold text-foreground">{title}</h3>
          )}
          {description && (
            <p className="text-sm text-muted-foreground">{description}</p>
          )}
        </div>
      )}
      <div
        className={cn(
          "grid grid-cols-1 gap-x-6 gap-y-5",
          columns === 2 && "sm:grid-cols-2"
        )}
      >
        {children}
      </div>
    </section>
  );
}

interface FormRowProps {
  /** Label text rendered to the left (sm+) or above (mobile) the control. */
  label: string;
  /** Associates the label with a control via its id. */
  htmlFor?: string;
  /** Optional helper text under the control. */
  hint?: string;
  /** Marks the field as required (adds a trailing asterisk). */
  required?: boolean;
  className?: string;
  children: React.ReactNode;
}

/**
 * FormRow — generic labeled row. Label sits left on sm+, stacks on mobile.
 * Use for any control that doesn't fit the FormField pattern.
 */
export function FormRow({
  label,
  htmlFor,
  hint,
  required,
  className,
  children,
}: FormRowProps) {
  return (
    <div
      className={cn(
        "grid grid-cols-1 gap-2 py-3 sm:grid-cols-[minmax(0,12rem)_minmax(0,1fr)] sm:gap-6 sm:py-4",
        className
      )}
    >
      <div className="flex flex-col gap-1 sm:pt-2">
        <Label htmlFor={htmlFor} required={required}>
          {label}
        </Label>
      </div>
      <div className="flex flex-col gap-1.5">
        {children}
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </div>
    </div>
  );
}
