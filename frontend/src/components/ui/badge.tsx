import * as React from"react";
import { cva, type VariantProps } from"class-variance-authority";
import { cn } from"@/lib/utils";

const badgeVariants = cva(
 ["inline-flex items-center gap-1 rounded-full","px-2.5 py-0.5 text-xs font-medium","transition-colors","whitespace-nowrap",
 ],
 {
 variants: {
 variant: {
 neutral: "bg-[hsl(var(--border))] text-foreground",
 plum: "bg-card text-foreground",
 burgundy: "bg-primary text-primary-foreground",
 soft: "bg-primary/10 text-primary",
 success: "border border-success/20 bg-success-muted text-success-muted-foreground",
 warning: "border border-warning/25 bg-warning-muted text-warning-muted-foreground",
 danger: "border border-destructive/20 bg-destructive-muted text-destructive-muted-foreground",
 info: "border border-info/20 bg-info-muted text-info-muted-foreground",
 linkedin: "bg-brand-linkedin text-brand-linkedin-foreground",
 outline: "border border-border text-foreground",
 alert: "bg-primary text-primary-foreground border border-primary animate-pulse-subtle font-semibold","alert-dark":"bg-card text-card-foreground border border-card font-semibold",
 },
 size: {
 sm: "px-2 py-0 text-[10px] h-4",
 md: "px-2.5 py-0.5 text-xs h-5",
 lg: "px-3 py-1 text-sm h-6",
 },
 uppercase: {
 true: "uppercase tracking-[0.08em]",
 false: "",
 },
 },
 defaultVariants: {
 variant: "neutral",
 size: "md",
 uppercase: false,
 },
 }
);

export interface BadgeProps
 extends React.HTMLAttributes<HTMLSpanElement>,
 VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, size, uppercase, ...props }: BadgeProps) {
 return (
 <span
 className={cn(badgeVariants({ variant, size, uppercase }), className)}
 {...props}
 />
 );
}

export { badgeVariants };
