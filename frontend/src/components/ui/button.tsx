"use client";

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Dynaminds button.
 *
 * Variants (per brandbook):
 *  - primary     : burgundy bg · white fg · default CTA
 *  - secondary   : plum bg · cream fg · strong secondary action
 *  - ghost       : transparent · plum fg · subtle tile wash on hover
 *  - tertiary    : text-only · burgundy underline hover
 *  - destructive : burgundy-700 · white · irreversible actions
 *  - outline     : transparent · hairline plum border · title fg
 *
 * All variants lift on hover via `-translate-y-[1px]` (per brandbook) and
 * show a 4px accent-soft focus ring handled globally in globals.css under
 * [data-ui="v2"].
 */

const buttonVariants = cva(
  [
    "inline-flex items-center justify-center gap-2 whitespace-nowrap",
    "font-medium transition-all duration-200 ease-in-out",
    "disabled:opacity-50 disabled:pointer-events-none",
    "focus-visible:outline-none",
    "select-none",
  ],
  {
    variants: {
      variant: {
        primary: [
          "bg-[hsl(var(--accent))] text-[hsl(var(--accent-foreground))]",
          "hover:bg-[hsl(var(--accent-strong))] hover:-translate-y-[1px]",
          "active:translate-y-0",
          "shadow-v2-s hover:shadow-v2-m",
        ],
        secondary: [
          "bg-[hsl(var(--bg-chrome))] text-[hsl(var(--text-onchrome))]",
          "hover:bg-[hsl(var(--bg-chrome))]/90 hover:-translate-y-[1px]",
          "shadow-v2-s hover:shadow-v2-m",
        ],
        ghost: [
          "bg-transparent text-[hsl(var(--text-title))]",
          "hover:bg-[hsl(var(--accent-soft))]",
        ],
        tertiary: [
          "bg-transparent text-[hsl(var(--accent))]",
          "hover:text-[hsl(var(--accent-strong))]",
          "underline-offset-4 hover:underline",
        ],
        destructive: [
          "bg-[hsl(var(--accent-strong))] text-white",
          "hover:bg-burgundy-800 hover:-translate-y-[1px]",
          "shadow-v2-s",
        ],
        outline: [
          "bg-transparent border border-[hsl(var(--border-strong))] text-[hsl(var(--text-title))]",
          "hover:bg-[hsl(var(--accent-soft))] hover:border-[hsl(var(--accent))]",
        ],
      },
      size: {
        sm: "h-8 px-3 text-xs rounded-v2-s",
        md: "h-10 px-4 text-sm rounded-v2-m",
        lg: "h-12 px-6 text-base rounded-v2-m",
        icon: "h-10 w-10 rounded-v2-m",
        "icon-sm": "h-8 w-8 rounded-v2-s",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "md",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { className, variant, size, asChild = false, loading = false, children, disabled, ...props },
    ref
  ) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        disabled={disabled || loading}
        {...props}
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
        {children}
      </Comp>
    );
  }
);
Button.displayName = "Button";

export { buttonVariants };
