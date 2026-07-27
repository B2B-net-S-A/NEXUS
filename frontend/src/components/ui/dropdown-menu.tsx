"use client";

import * as React from"react";
import * as DropdownMenuPrimitive from"@radix-ui/react-dropdown-menu";
import { Check, ChevronRight, Circle } from"lucide-react";
import { cn } from"@/lib/utils";

const DropdownMenu = DropdownMenuPrimitive.Root;
const DropdownMenuTrigger = DropdownMenuPrimitive.Trigger;
const DropdownMenuGroup = DropdownMenuPrimitive.Group;
const DropdownMenuPortal = DropdownMenuPrimitive.Portal;
const DropdownMenuSub = DropdownMenuPrimitive.Sub;
const DropdownMenuRadioGroup = DropdownMenuPrimitive.RadioGroup;

const DropdownMenuSubTrigger = React.forwardRef<
 React.ComponentRef<typeof DropdownMenuPrimitive.SubTrigger>,
 React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.SubTrigger> & {
 inset?: boolean;
 }
>(({ className, inset, children, ...props }, ref) => (
 <DropdownMenuPrimitive.SubTrigger
 ref={ref}
 className={cn("flex cursor-pointer select-none items-center rounded-md px-2 py-1.5 text-sm outline-hidden","focus:bg-primary/10 data-[state=open]:bg-primary/10",
 inset &&"pl-8",
 className
 )}
 {...props}
 >
 {children}
 <ChevronRight className="ml-auto h-4 w-4" />
 </DropdownMenuPrimitive.SubTrigger>
));
DropdownMenuSubTrigger.displayName ="DropdownMenuSubTrigger";

const DropdownMenuSubContent = React.forwardRef<
 React.ComponentRef<typeof DropdownMenuPrimitive.SubContent>,
 React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.SubContent>
>(({ className, ...props }, ref) => (
 <DropdownMenuPrimitive.SubContent
 ref={ref}
 className={cn("z-50 min-w-32 overflow-hidden rounded-lg p-1","bg-card text-foreground","border border-border shadow-md","data-[state=open]:animate-fadeIn",
 className
 )}
 {...props}
 />
));
DropdownMenuSubContent.displayName ="DropdownMenuSubContent";

const DropdownMenuContent = React.forwardRef<
 React.ComponentRef<typeof DropdownMenuPrimitive.Content>,
 React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Content>
>(({ className, sideOffset = 6, align ="end", ...props }, ref) => (
 <DropdownMenuPrimitive.Portal>
 <DropdownMenuPrimitive.Content
 ref={ref}
 sideOffset={sideOffset}
 align={align}
 className={cn("z-50 min-w-40 overflow-hidden rounded-lg p-1","bg-card text-foreground","border border-border shadow-md","data-[state=open]:animate-fadeIn",
 className
 )}
 {...props}
 />
 </DropdownMenuPrimitive.Portal>
));
DropdownMenuContent.displayName ="DropdownMenuContent";

const DropdownMenuItem = React.forwardRef<
 React.ComponentRef<typeof DropdownMenuPrimitive.Item>,
 React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Item> & {
 inset?: boolean;
 danger?: boolean;
 }
>(({ className, inset, danger, ...props }, ref) => (
 <DropdownMenuPrimitive.Item
 ref={ref}
 className={cn("relative flex cursor-pointer select-none items-center gap-2 rounded-md px-2 py-1.5 text-sm outline-hidden","transition-colors focus:bg-primary/10 focus:text-foreground","data-disabled:pointer-events-none data-disabled:opacity-50",
 inset &&"pl-8",
 danger &&"text-primary focus:bg-primary/10",
 className
 )}
 {...props}
 />
));
DropdownMenuItem.displayName ="DropdownMenuItem";

const DropdownMenuCheckboxItem = React.forwardRef<
 React.ComponentRef<typeof DropdownMenuPrimitive.CheckboxItem>,
 React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.CheckboxItem>
>(({ className, children, checked, ...props }, ref) => (
 <DropdownMenuPrimitive.CheckboxItem
 ref={ref}
 checked={checked}
 className={cn("relative flex cursor-pointer select-none items-center rounded-md py-1.5 pl-8 pr-2 text-sm outline-hidden","focus:bg-primary/10","data-disabled:pointer-events-none data-disabled:opacity-50",
 className
 )}
 {...props}
 >
 <span className="absolute left-2 flex h-4 w-4 items-center justify-center">
 <DropdownMenuPrimitive.ItemIndicator>
 <Check className="h-4 w-4 text-primary" />
 </DropdownMenuPrimitive.ItemIndicator>
 </span>
 {children}
 </DropdownMenuPrimitive.CheckboxItem>
));
DropdownMenuCheckboxItem.displayName ="DropdownMenuCheckboxItem";

const DropdownMenuRadioItem = React.forwardRef<
 React.ComponentRef<typeof DropdownMenuPrimitive.RadioItem>,
 React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.RadioItem>
>(({ className, children, ...props }, ref) => (
 <DropdownMenuPrimitive.RadioItem
 ref={ref}
 className={cn("relative flex cursor-pointer select-none items-center rounded-md py-1.5 pl-8 pr-2 text-sm outline-hidden","focus:bg-primary/10","data-disabled:pointer-events-none data-disabled:opacity-50",
 className
 )}
 {...props}
 >
 <span className="absolute left-2 flex h-4 w-4 items-center justify-center">
 <DropdownMenuPrimitive.ItemIndicator>
 <Circle className="h-2 w-2 fill-[hsl(var(--primary))] text-primary" />
 </DropdownMenuPrimitive.ItemIndicator>
 </span>
 {children}
 </DropdownMenuPrimitive.RadioItem>
));
DropdownMenuRadioItem.displayName ="DropdownMenuRadioItem";

const DropdownMenuLabel = React.forwardRef<
 React.ComponentRef<typeof DropdownMenuPrimitive.Label>,
 React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Label> & { inset?: boolean }
>(({ className, inset, ...props }, ref) => (
 <DropdownMenuPrimitive.Label
 ref={ref}
 className={cn("px-2 py-1.5 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground",
 inset &&"pl-8",
 className
 )}
 {...props}
 />
));
DropdownMenuLabel.displayName ="DropdownMenuLabel";

const DropdownMenuSeparator = React.forwardRef<
 React.ComponentRef<typeof DropdownMenuPrimitive.Separator>,
 React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Separator>
>(({ className, ...props }, ref) => (
 <DropdownMenuPrimitive.Separator
 ref={ref}
 className={cn("-mx-1 my-1 h-px bg-[hsl(var(--border))]", className)}
 {...props}
 />
));
DropdownMenuSeparator.displayName ="DropdownMenuSeparator";

const DropdownMenuShortcut = ({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) => (
 <span
 className={cn("ml-auto text-[10px] font-mono tracking-widest text-muted-foreground",
 className
 )}
 {...props}
 />
);
DropdownMenuShortcut.displayName ="DropdownMenuShortcut";

export {
 DropdownMenu,
 DropdownMenuTrigger,
 DropdownMenuContent,
 DropdownMenuItem,
 DropdownMenuCheckboxItem,
 DropdownMenuRadioItem,
 DropdownMenuLabel,
 DropdownMenuSeparator,
 DropdownMenuShortcut,
 DropdownMenuGroup,
 DropdownMenuPortal,
 DropdownMenuSub,
 DropdownMenuSubContent,
 DropdownMenuSubTrigger,
 DropdownMenuRadioGroup,
};
