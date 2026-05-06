"use client";

import * as React from"react";
import { Command as CommandPrimitive } from"cmdk";
import { Search } from"lucide-react";
import { cn } from"@/lib/utils";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from"./dialog";

/**
 * Command palette built on cmdk. Use <CommandDialog> for ⌘K-style palette;
 * use the lower-level <Command> primitives to embed an inline searcher.
 */

const Command = React.forwardRef<
 React.ComponentRef<typeof CommandPrimitive>,
 React.ComponentPropsWithoutRef<typeof CommandPrimitive>
>(({ className, ...props }, ref) => (
 <CommandPrimitive
 ref={ref}
 className={cn("flex h-full w-full flex-col overflow-hidden","bg-card text-foreground","rounded-xl",
 className
 )}
 {...props}
 />
));
Command.displayName ="Command";

interface CommandDialogProps extends React.ComponentProps<typeof Dialog> {
 title?: string;
 description?: string;
 children: React.ReactNode;
}

const CommandDialog = ({ title ="Wyszukaj", description ="Szybki dostęp do kandydatów, ofert i akcji.", children, ...props }: CommandDialogProps) => (
 <Dialog {...props}>
 <DialogContent size="lg" className="p-0 overflow-hidden" hideClose>
 <div className="sr-only">
 <DialogTitle>{title}</DialogTitle>
 <DialogDescription>{description}</DialogDescription>
 </div>
 <Command className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.12em] [&_[cmdk-group-heading]]:text-muted-foreground [&_[cmdk-group]]:px-1 [&_[cmdk-group]]:pb-2 [&_[cmdk-input-wrapper]_svg]:h-4 [&_[cmdk-input-wrapper]_svg]:w-4 [&_[cmdk-input]]:h-12 [&_[cmdk-item]]:px-2 [&_[cmdk-item]]:py-2.5 [&_[cmdk-item]_svg]:h-4 [&_[cmdk-item]_svg]:w-4">
 {children}
 </Command>
 </DialogContent>
 </Dialog>
);

const CommandInput = React.forwardRef<
 React.ComponentRef<typeof CommandPrimitive.Input>,
 React.ComponentPropsWithoutRef<typeof CommandPrimitive.Input>
>(({ className, ...props }, ref) => (
 <div className="flex items-center gap-2 border-b border-border px-4" cmdk-input-wrapper="">
 <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
 <CommandPrimitive.Input
 ref={ref}
 className={cn("flex h-12 w-full rounded-none bg-transparent py-3 text-sm outline-none","placeholder:text-muted-foreground","disabled:cursor-not-allowed disabled:opacity-50",
 className
 )}
 {...props}
 />
 </div>
));
CommandInput.displayName ="CommandInput";

const CommandList = React.forwardRef<
 React.ComponentRef<typeof CommandPrimitive.List>,
 React.ComponentPropsWithoutRef<typeof CommandPrimitive.List>
>(({ className, ...props }, ref) => (
 <CommandPrimitive.List
 ref={ref}
 className={cn("max-h-[420px] overflow-y-auto overflow-x-hidden", className)}
 {...props}
 />
));
CommandList.displayName ="CommandList";

const CommandEmpty = React.forwardRef<
 React.ComponentRef<typeof CommandPrimitive.Empty>,
 React.ComponentPropsWithoutRef<typeof CommandPrimitive.Empty>
>((props, ref) => (
 <CommandPrimitive.Empty
 ref={ref}
 className="py-6 text-center text-sm text-muted-foreground"
 {...props}
 />
));
CommandEmpty.displayName ="CommandEmpty";

const CommandGroup = React.forwardRef<
 React.ComponentRef<typeof CommandPrimitive.Group>,
 React.ComponentPropsWithoutRef<typeof CommandPrimitive.Group>
>(({ className, ...props }, ref) => (
 <CommandPrimitive.Group
 ref={ref}
 className={cn("overflow-hidden text-foreground", className)}
 {...props}
 />
));
CommandGroup.displayName ="CommandGroup";

const CommandSeparator = React.forwardRef<
 React.ComponentRef<typeof CommandPrimitive.Separator>,
 React.ComponentPropsWithoutRef<typeof CommandPrimitive.Separator>
>(({ className, ...props }, ref) => (
 <CommandPrimitive.Separator
 ref={ref}
 className={cn("h-px bg-[hsl(var(--border-subtle))]", className)}
 {...props}
 />
));
CommandSeparator.displayName ="CommandSeparator";

const CommandItem = React.forwardRef<
 React.ComponentRef<typeof CommandPrimitive.Item>,
 React.ComponentPropsWithoutRef<typeof CommandPrimitive.Item>
>(({ className, ...props }, ref) => (
 <CommandPrimitive.Item
 ref={ref}
 className={cn("relative flex cursor-pointer select-none items-center gap-2 rounded-md px-2 py-2 text-sm outline-none","data-[selected=true]:bg-primary/10 data-[selected=true]:text-foreground","data-[disabled=true]:pointer-events-none data-[disabled=true]:opacity-50",
 className
 )}
 {...props}
 />
));
CommandItem.displayName ="CommandItem";

const CommandShortcut = ({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) => (
 <span
 className={cn("ml-auto text-[10px] font-mono tracking-widest text-muted-foreground",
 className
 )}
 {...props}
 />
);
CommandShortcut.displayName ="CommandShortcut";

export {
 Command,
 CommandDialog,
 CommandInput,
 CommandList,
 CommandEmpty,
 CommandGroup,
 CommandItem,
 CommandShortcut,
 CommandSeparator,
};
