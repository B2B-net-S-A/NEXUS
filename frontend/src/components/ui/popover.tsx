"use client";

import * as React from"react";
import * as PopoverPrimitive from"@radix-ui/react-popover";
import { cn } from"@/lib/utils";

const Popover = PopoverPrimitive.Root;
const PopoverTrigger = PopoverPrimitive.Trigger;
const PopoverAnchor = PopoverPrimitive.Anchor;
const PopoverClose = PopoverPrimitive.Close;

const PopoverContent = React.forwardRef<
 React.ComponentRef<typeof PopoverPrimitive.Content>,
 React.ComponentPropsWithoutRef<typeof PopoverPrimitive.Content>
>(({ className, align ="start", sideOffset = 8, ...props }, ref) => (
 <PopoverPrimitive.Portal>
 <PopoverPrimitive.Content
 ref={ref}
 align={align}
 sideOffset={sideOffset}
 className={cn("z-50 min-w-48 rounded-lg p-3","bg-card text-foreground","border border-border shadow-md","data-[state=open]:animate-fadeIn","focus:outline-hidden",
 className
 )}
 {...props}
 />
 </PopoverPrimitive.Portal>
));
PopoverContent.displayName ="PopoverContent";

export { Popover, PopoverTrigger, PopoverAnchor, PopoverContent, PopoverClose };
