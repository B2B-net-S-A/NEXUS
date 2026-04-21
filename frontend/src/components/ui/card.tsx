import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const cardVariants = cva(
  [
    "bg-[hsl(var(--bg-surface))] text-[hsl(var(--text-body))]",
    "border border-[hsl(var(--border-subtle))]",
    "transition-shadow",
  ],
  {
    variants: {
      variant: {
        default: "shadow-v2-s",
        elevated: "shadow-v2-m",
        flat: "shadow-none",
        interactive: "shadow-v2-s hover:shadow-v2-m hover:-translate-y-[1px] transition-all cursor-pointer",
      },
      size: {
        sm: "rounded-v2-s p-3",
        md: "rounded-v2-m p-5",
        lg: "rounded-v2-l p-6",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "md",
    },
  }
);

export interface CardProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof cardVariants> {}

export const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ className, variant, size, ...props }, ref) => (
    <div ref={ref} className={cn(cardVariants({ variant, size }), className)} {...props} />
  )
);
Card.displayName = "Card";

export const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("flex flex-col gap-1 mb-4", className)} {...props} />
  )
);
CardHeader.displayName = "CardHeader";

export const CardTitle = React.forwardRef<HTMLHeadingElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h3
      ref={ref}
      className={cn(
        "font-display text-lg font-bold text-[hsl(var(--text-title))] tracking-[-0.01em]",
        className
      )}
      {...props}
    />
  )
);
CardTitle.displayName = "CardTitle";

export const CardDescription = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLParagraphElement>>(
  ({ className, ...props }, ref) => (
    <p ref={ref} className={cn("text-sm text-[hsl(var(--text-muted))]", className)} {...props} />
  )
);
CardDescription.displayName = "CardDescription";

export const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => <div ref={ref} className={cn(className)} {...props} />
);
CardContent.displayName = "CardContent";

export const CardFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("flex items-center gap-2 mt-4 pt-4 border-t border-[hsl(var(--border-subtle))]", className)}
      {...props}
    />
  )
);
CardFooter.displayName = "CardFooter";

export { cardVariants };
