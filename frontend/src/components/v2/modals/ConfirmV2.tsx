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

export interface ConfirmRequest {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "default" | "destructive";
}

/**
 * Obietnicowe potwierdzenie na ConfirmV2 — zamiennik `window.confirm()`
 * (runda 11 audytu, FRONT). Natywny dialog zamraża automatyzację przeglądarki
 * i odstaje od UI; ten zwraca `Promise<boolean>`, więc wołający zmienia tylko
 * `confirm(...)` na `await askConfirm({...})`.
 *
 * - Anulowanie (przycisk, Esc, klik obok) = `false`, nic się nie dzieje.
 * - Potwierdzenie rozwiązuje obietnicę RAZ — drugie kliknięcie w trakcie
 *   zamykania nie wykona akcji drugi raz.
 * - `confirmDialog` wyrenderuj raz w komponencie, który woła `askConfirm`.
 */
export function useConfirmV2(): {
  askConfirm: (request: ConfirmRequest) => Promise<boolean>;
  confirmDialog: React.ReactNode;
} {
  const [request, setRequest] = React.useState<ConfirmRequest | null>(null);
  const [open, setOpen] = React.useState(false);
  const resolverRef = React.useRef<((value: boolean) => void) | null>(null);

  const settle = React.useCallback((value: boolean) => {
    const resolve = resolverRef.current;
    resolverRef.current = null;
    setOpen(false);
    resolve?.(value);
  }, []);

  React.useEffect(
    () => () => {
      resolverRef.current?.(false);
      resolverRef.current = null;
    },
    [],
  );

  const askConfirm = React.useCallback((next: ConfirmRequest) => {
    // Poprzednie, nierozstrzygnięte pytanie traktujemy jak anulowane.
    resolverRef.current?.(false);
    return new Promise<boolean>((resolve) => {
      resolverRef.current = resolve;
      setRequest(next);
      setOpen(true);
    });
  }, []);

  const confirmDialog = request ? (
    <ConfirmV2
      open={open}
      onOpenChange={(next) => {
        if (!next) settle(false);
      }}
      title={request.title}
      description={request.description}
      confirmLabel={request.confirmLabel}
      cancelLabel={request.cancelLabel}
      variant={request.variant}
      onConfirm={() => settle(true)}
    />
  ) : null;

  return { askConfirm, confirmDialog };
}
