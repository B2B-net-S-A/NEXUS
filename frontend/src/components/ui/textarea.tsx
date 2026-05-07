"use client";

import * as React from"react";
import { cn } from"@/lib/utils";

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
 invalid?: boolean;
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
 ({ className, invalid, rows = 4, ...props }, ref) => (
 <textarea
 ref={ref}
 rows={rows}
 aria-invalid={invalid || undefined}
 className={cn("w-full min-h-[80px] px-3 py-2 text-sm bg-card text-foreground","border border-border rounded-lg","placeholder:text-muted-foreground","transition-colors duration-150 resize-y","focus:outline-none focus:border-primary","disabled:bg-[hsl(var(--border))]/30 disabled:cursor-not-allowed",
 invalid &&"border-primary focus:border-[hsl(var(--primary))]",
 className
 )}
 {...props}
 />
 )
);
Textarea.displayName ="Textarea";
