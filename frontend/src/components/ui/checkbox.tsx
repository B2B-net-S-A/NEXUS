"use client";

import * as React from"react";
import * as CheckboxPrimitive from"@radix-ui/react-checkbox";
import { Check, Minus } from"lucide-react";
import { cn } from"@/lib/utils";

export const Checkbox = React.forwardRef<
 React.ComponentRef<typeof CheckboxPrimitive.Root>,
 React.ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>
>(({ className, ...props }, ref) => (
 <CheckboxPrimitive.Root
 ref={ref}
 className={cn("peer h-4 w-4 shrink-0 rounded-md border border-border","bg-card","transition-colors duration-150","hover:border-primary","disabled:cursor-not-allowed disabled:opacity-50","data-[state=checked]:bg-primary data-[state=checked]:border-primary data-[state=checked]:text-white","data-[state=indeterminate]:bg-primary data-[state=indeterminate]:border-primary data-[state=indeterminate]:text-white",
 className
 )}
 {...props}
 >
 <CheckboxPrimitive.Indicator className="flex items-center justify-center text-current">
 {props.checked ==="indeterminate" ? (
 <Minus className="h-3 w-3" />
 ) : (
 <Check className="h-3 w-3" />
 )}
 </CheckboxPrimitive.Indicator>
 </CheckboxPrimitive.Root>
));
Checkbox.displayName ="Checkbox";
