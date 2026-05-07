"use client";

import * as React from"react";
import { AlertTriangle } from"lucide-react";
import {
 Dialog,
 DialogBody,
 DialogContent,
 DialogDescription,
 DialogFooter,
 DialogHeader,
 DialogTitle,
} from"@/components/ui/dialog";
import { Button } from"@/components/ui/button";

interface Props {
 open: boolean;
 onOpenChange: (open: boolean) => void;
 title: string;
 description?: string;
 confirmLabel?: string;
 cancelLabel?: string;
 variant?:"default" |"destructive";
 onConfirm: () => void;
 loading?: boolean;
}

/**
 * ConfirmV2 — reusable confirmation dialog. Replaces window.confirm() +
 * ad-hoc confirm patterns scattered across v1.
 */
export function ConfirmV2({
 open,
 onOpenChange,
 title,
 description,
 confirmLabel ="Potwierdź",
 cancelLabel ="Anuluj",
 variant ="default",
 onConfirm,
 loading,
}: Props) {
 return (
 <Dialog open={open} onOpenChange={onOpenChange}>
 <DialogContent size="sm">
 <DialogHeader>
 <div className="flex items-center gap-2">
 {variant === "destructive" && (
 <AlertTriangle className="h-4 w-4 text-primary" />
 )}
 <DialogTitle>{title}</DialogTitle>
 </div>
 {description && <DialogDescription>{description}</DialogDescription>}
 </DialogHeader>

 <DialogBody />

 <DialogFooter>
 <Button
 variant="ghost"
 onClick={() => onOpenChange(false)}
 disabled={loading}
 >
 {cancelLabel}
 </Button>
 <Button
 variant={variant === "destructive" ?"destructive" :"primary"}
 onClick={onConfirm}
 loading={loading}
 >
 {confirmLabel}
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
 );
}
