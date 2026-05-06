import * as React from"react";
import { cn } from"@/lib/utils";

/**
 * Keyboard shortcut indicator. Renders monospace pill.
 * Usage: <Kbd>⌘</Kbd><Kbd>K</Kbd> or <Kbd>Esc</Kbd>
 */
export function Kbd({
 className,
 children,
 ...props
}: React.HTMLAttributes<HTMLElement>) {
 return (
 <kbd
 className={cn("inline-flex items-center justify-center","h-5 min-w-[1.25rem] px-1.5","text-[10px] font-mono font-medium","rounded-md bg-[hsl(var(--border-subtle))] text-foreground","border border-border shadow-sm",
 className
 )}
 {...props}
 >
 {children}
 </kbd>
 );
}
