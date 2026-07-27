import * as React from"react";
import { cva, type VariantProps } from"class-variance-authority";
import { cn } from"@/lib/utils";

const cardVariants = cva(
 ["bg-card text-foreground","border border-border","transition-shadow",
 ],
 {
 variants: {
 variant: {
 default: "shadow-xs",
 elevated: "shadow-xs",
 flat: "shadow-none",
 interactive: "shadow-xs hover:shadow-xs transition-all cursor-pointer",
 },
 size: {
 sm: "rounded-md p-3",
 md: "rounded-lg p-5",
 lg: "rounded-xl p-6",
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
Card.displayName ="Card";

export const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
 ({ className, ...props }, ref) => (
 <div ref={ref} className={cn("flex flex-col gap-1 mb-4", className)} {...props} />
 )
);
CardHeader.displayName ="CardHeader";

export const CardTitle = React.forwardRef<HTMLHeadingElement, React.HTMLAttributes<HTMLHeadingElement>>(
 ({ className, ...props }, ref) => (
 <h3
 ref={ref}
 className={cn("font-semibold text-lg font-bold text-foreground tracking-heading",
 className
 )}
 {...props}
 />
 )
);
CardTitle.displayName ="CardTitle";

export const CardDescription = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLParagraphElement>>(
 ({ className, ...props }, ref) => (
 <p ref={ref} className={cn("text-sm text-muted-foreground", className)} {...props} />
 )
);
CardDescription.displayName ="CardDescription";

export const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
 ({ className, ...props }, ref) => <div ref={ref} className={cn(className)} {...props} />
);
CardContent.displayName ="CardContent";

export const CardFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
 ({ className, ...props }, ref) => (
 <div
 ref={ref}
 className={cn("flex items-center gap-2 mt-4 pt-4 border-t border-border", className)}
 {...props}
 />
 )
);
CardFooter.displayName ="CardFooter";

export { cardVariants };
