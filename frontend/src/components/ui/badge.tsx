import * as React from"react";
import { cva, type VariantProps } from"class-variance-authority";
import { cn } from"@/lib/utils";

const badgeVariants = cva(
 ["inline-flex items-center gap-1 rounded-full","px-2.5 py-0.5 text-xs font-medium","transition-colors","whitespace-nowrap",
 ],
 {
 variants: {
 variant: {
 neutral:"bg-[hsl(var(--border))] text-foreground",
 plum:"bg-card text-foreground",
 burgundy:"bg-primary text-primary-foreground",
 soft:"bg-primary/10 text-primary",
 success:"bg-[#dfecd9] text-[#1d5e31]",
 warning:"bg-amber-50 text-amber-800 border border-amber-200",
 danger:"bg-[#f4e0e3] text-[#6b1120]",
 info:"bg-[#e3dfe5] text-foreground",
 outline:"border border-border text-foreground",
 alert:"bg-primary text-white border border-[hsl(var(--primary))] animate-pulse-subtle font-semibold","alert-dark":"bg-card text-white border border-[hsl(var(--card))] font-semibold",
 },
 size: {
 sm:"px-2 py-0 text-[10px] h-4",
 md:"px-2.5 py-0.5 text-xs h-5",
 lg:"px-3 py-1 text-sm h-6",
 },
 uppercase: {
 true:"uppercase tracking-[0.08em]",
 false:"",
 },
 },
 defaultVariants: {
 variant:"neutral",
 size:"md",
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
