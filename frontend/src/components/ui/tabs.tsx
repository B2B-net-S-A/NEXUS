"use client";

import * as React from"react";
import * as TabsPrimitive from"@radix-ui/react-tabs";
import { cn } from"@/lib/utils";

const Tabs = TabsPrimitive.Root;

const TabsList = React.forwardRef<
 React.ComponentRef<typeof TabsPrimitive.List>,
 React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
 <TabsPrimitive.List
 ref={ref}
 className={cn("inline-flex items-center gap-1","border-b border-border",
 className
 )}
 {...props}
 />
));
TabsList.displayName ="TabsList";

const TabsTrigger = React.forwardRef<
 React.ComponentRef<typeof TabsPrimitive.Trigger>,
 React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
 <TabsPrimitive.Trigger
 ref={ref}
 className={cn("relative inline-flex items-center gap-2","px-3 py-2 text-sm font-medium","text-muted-foreground hover:text-foreground","transition-colors focus:outline-none","border-b-2 border-transparent -mb-px","data-[state=active]:text-primary","data-[state=active]:border-primary","disabled:opacity-50 disabled:pointer-events-none",
 className
 )}
 {...props}
 />
));
TabsTrigger.displayName ="TabsTrigger";

const TabsContent = React.forwardRef<
 React.ComponentRef<typeof TabsPrimitive.Content>,
 React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
 <TabsPrimitive.Content
 ref={ref}
 className={cn("mt-4 focus:outline-none","data-[state=active]:animate-fadeIn",
 className
 )}
 {...props}
 />
));
TabsContent.displayName ="TabsContent";

export { Tabs, TabsList, TabsTrigger, TabsContent };
