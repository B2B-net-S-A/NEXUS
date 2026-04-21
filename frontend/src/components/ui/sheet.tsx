"use client";

import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Side sheet — built on Radix Dialog. Replaces ad-hoc modals for forms with
 * 5+ fields (Screening, Scorecard, SendEmail). Slides in from side.
 */

const Sheet = DialogPrimitive.Root;
const SheetTrigger = DialogPrimitive.Trigger;
const SheetPortal = DialogPrimitive.Portal;
const SheetClose = DialogPrimitive.Close;

const SheetOverlay = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      "fixed inset-0 z-40 bg-[hsl(var(--bg-chrome))]/50 backdrop-blur-[2px]",
      "data-[state=open]:animate-fadeIn",
      className
    )}
    {...props}
  />
));
SheetOverlay.displayName = "SheetOverlay";

const sheetSideClasses: Record<"right" | "left" | "top" | "bottom", string> = {
  right:
    "inset-y-0 right-0 h-full w-full sm:max-w-xl border-l data-[state=open]:animate-slide-in-right",
  left:
    "inset-y-0 left-0 h-full w-full sm:max-w-xl border-r data-[state=open]:animate-slide-in-right",
  top:
    "inset-x-0 top-0 h-auto max-h-[85vh] border-b data-[state=open]:animate-fadeIn",
  bottom:
    "inset-x-0 bottom-0 h-auto max-h-[85vh] border-t data-[state=open]:animate-slide-in-bottom",
};

const sheetWidths: Record<string, string> = {
  sm: "sm:max-w-md",
  md: "sm:max-w-xl",
  lg: "sm:max-w-2xl",
  xl: "sm:max-w-3xl",
  "2xl": "sm:max-w-5xl",
};

interface SheetContentProps
  extends React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> {
  side?: "right" | "left" | "top" | "bottom";
  size?: keyof typeof sheetWidths;
  hideClose?: boolean;
}

const SheetContent = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Content>,
  SheetContentProps
>(({ side = "right", size = "md", className, children, hideClose, ...props }, ref) => (
  <SheetPortal>
    <SheetOverlay />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        "fixed z-50 flex flex-col bg-[hsl(var(--bg-surface))] text-[hsl(var(--text-body))]",
        "border-[hsl(var(--border-subtle))] shadow-v2-xl",
        sheetSideClasses[side],
        size && sheetWidths[size],
        className
      )}
      {...props}
    >
      {children}
      {!hideClose && (
        <DialogPrimitive.Close
          className={cn(
            "absolute right-4 top-4 rounded-v2-s p-1",
            "text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text-title))]",
            "hover:bg-[hsl(var(--accent-soft))] transition-colors",
            "focus:outline-none"
          )}
        >
          <X className="h-4 w-4" />
          <span className="sr-only">Zamknij</span>
        </DialogPrimitive.Close>
      )}
    </DialogPrimitive.Content>
  </SheetPortal>
));
SheetContent.displayName = "SheetContent";

const SheetHeader = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-col gap-1 px-6 pt-6 pb-4",
      "border-b border-[hsl(var(--border-subtle))]",
      className
    )}
    {...props}
  />
);
SheetHeader.displayName = "SheetHeader";

const SheetBody = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("flex-1 px-6 py-4 overflow-y-auto", className)} {...props} />
);
SheetBody.displayName = "SheetBody";

const SheetFooter = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-col-reverse sm:flex-row sm:justify-end sm:gap-2 gap-2 px-6 py-4",
      "border-t border-[hsl(var(--border-subtle))] bg-[hsl(var(--bg-canvas))]/40",
      className
    )}
    {...props}
  />
);
SheetFooter.displayName = "SheetFooter";

const SheetTitle = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn(
      "font-display text-lg font-bold tracking-[-0.01em] text-[hsl(var(--text-title))]",
      className
    )}
    {...props}
  />
));
SheetTitle.displayName = "SheetTitle";

const SheetDescription = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn("text-sm text-[hsl(var(--text-muted))]", className)}
    {...props}
  />
));
SheetDescription.displayName = "SheetDescription";

export {
  Sheet,
  SheetTrigger,
  SheetPortal,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetBody,
  SheetFooter,
  SheetTitle,
  SheetDescription,
};
