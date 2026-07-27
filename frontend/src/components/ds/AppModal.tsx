"use client";

import * as React from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

type AppModalSize = "sm" | "md" | "lg";

const sizeClasses: Record<AppModalSize, string> = {
  sm: "max-w-[24rem]",
  md: "max-w-lg",
  lg: "max-w-2xl",
};

export interface AppModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  size?: AppModalSize;
  footer?: React.ReactNode;
  children: React.ReactNode;
}

export function AppModal({
  open,
  onOpenChange,
  title,
  description,
  size = "md",
  footer,
  children,
}: AppModalProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(sizeClasses[size])}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description ? <DialogDescription>{description}</DialogDescription> : null}
        </DialogHeader>
        <div className="px-6 py-4 overflow-y-auto flex-1 min-h-0">{children}</div>
        {footer ? (
          <DialogFooter className="flex justify-end gap-2">{footer}</DialogFooter>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
