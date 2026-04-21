"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  invalid?: boolean;
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, invalid, rows = 4, ...props }, ref) => (
    <textarea
      ref={ref}
      rows={rows}
      aria-invalid={invalid || undefined}
      className={cn(
        "w-full min-h-[80px] px-3 py-2 text-sm bg-[hsl(var(--bg-surface))] text-[hsl(var(--text-body))]",
        "border border-[hsl(var(--border-subtle))] rounded-v2-m",
        "placeholder:text-[hsl(var(--text-muted))]",
        "transition-colors duration-150 resize-y",
        "focus:outline-none focus:border-[hsl(var(--accent))]",
        "disabled:bg-[hsl(var(--border-subtle))]/30 disabled:cursor-not-allowed",
        invalid && "border-[hsl(var(--accent))] focus:border-[hsl(var(--accent-strong))]",
        className
      )}
      {...props}
    />
  )
);
Textarea.displayName = "Textarea";
