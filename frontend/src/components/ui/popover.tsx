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
 // z-110: nad oknem `Modal` z AppShell (overlay z-100). Przy z-50 lista
 // „Współpracownicy” w oknie edycji rekrutacji otwierała się POD oknem
 // (zgłoszenie 30.09.2026). To samo w dropdown-menu, select i tooltip.
 className={cn("z-110 min-w-48 rounded-lg p-3",
 // Nie wychodzi poza ekran telefonu (w poziomie ani w pionie) — dół długiej
 // treści przewija się zamiast znikać pod krawędzią.
 "max-h-(--radix-popover-content-available-height) max-w-[calc(100vw-1rem)] overflow-y-auto","bg-card text-foreground","border border-border shadow-md","data-[state=open]:animate-fadeIn","focus:outline-hidden",
 className
 )}
 {...props}
 />
 </PopoverPrimitive.Portal>
));
PopoverContent.displayName ="PopoverContent";

export { Popover, PopoverTrigger, PopoverAnchor, PopoverContent, PopoverClose };
