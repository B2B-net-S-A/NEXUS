"use client";

import * as React from"react";
import { cn } from"@/lib/utils";

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
 invalid?: boolean;
 leadingIcon?: React.ReactNode;
 trailingIcon?: React.ReactNode;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
 ({ className, type ="text", invalid, leadingIcon, trailingIcon, ...props }, ref) => {
 const input = (
 <input
 ref={ref}
 type={type}
 aria-invalid={invalid || undefined}
 className={cn("w-full h-10 px-3 py-2 text-sm bg-card text-foreground","border border-border rounded-lg","placeholder:text-muted-foreground","transition-colors duration-150","focus:outline-none focus:border-primary","disabled:bg-[hsl(var(--border-subtle))]/30 disabled:cursor-not-allowed disabled:text-muted-foreground",
 invalid &&"border-primary focus:border-[hsl(var(--accent-strong))]",
 leadingIcon &&"pl-9",
 trailingIcon &&"pr-9",
 className
 )}
 {...props}
 />
 );

 if (!leadingIcon && !trailingIcon) return input;

 return (
 <div className="relative">
 {leadingIcon && (
 <span
 aria-hidden="true"
 className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
 >
 {leadingIcon}
 </span>
 )}
 {input}
 {trailingIcon && (
 <span
 aria-hidden="true"
 className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground"
 >
 {trailingIcon}
 </span>
 )}
 </div>
 );
 }
);
Input.displayName ="Input";
