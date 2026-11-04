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
import { Textarea } from"@/components/ui/textarea";

/** Pole tekstowe w oknie potwierdzenia (np. powód anulowania). */
export interface ConfirmField {
 label: string;
 placeholder?: string;
 /** Najmniej znaków po przycięciu, żeby przycisk potwierdzenia działał. */
 minLength?: number;
 maxLength?: number;
}

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
 field?: ConfirmField & { value: string; onChange: (value: string) => void };
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
 field,
}: Props) {
 const fieldId = React.useId();
 const fieldShort =
 field !== undefined && field.value.trim().length < (field.minLength ?? 1);
 return (
 <Dialog open={open} onOpenChange={onOpenChange}>
 <DialogContent size="sm">
 {/* Bez treści między opisem a stopką: linia stopki wystarcza, druga
 (dolna krawędź nagłówka) dawałaby podwójną kreskę. */}
 <DialogHeader className="border-b-0">
 <div className="flex items-center gap-2">
 {variant === "destructive" && (
 <AlertTriangle className="h-4 w-4 text-primary" />
 )}
 <DialogTitle>{title}</DialogTitle>
 </div>
 {description && <DialogDescription>{description}</DialogDescription>}
 </DialogHeader>

 {field && (
 <DialogBody className="space-y-1.5 pt-0">
 <label htmlFor={fieldId} className="text-sm font-medium">
 {field.label}
 </label>
 <Textarea
 id={fieldId}
 rows={3}
 autoFocus
 value={field.value}
 placeholder={field.placeholder}
 maxLength={field.maxLength}
 onChange={(event) => field.onChange(event.target.value)}
 />
 </DialogBody>
 )}

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
 disabled={fieldShort}
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

export interface ReasonRequest extends ConfirmRequest {
  field: ConfirmField;
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
 * - `askReason` to samo pytanie z polem tekstowym (np. powód anulowania):
 *   zwraca przycięty tekst albo `null` przy anulowaniu.
 * - `confirmDialog` wyrenderuj raz w komponencie, który woła `askConfirm`.
 */
export function useConfirmV2(): {
  askConfirm: (request: ConfirmRequest) => Promise<boolean>;
  askReason: (request: ReasonRequest) => Promise<string | null>;
  confirmDialog: React.ReactNode;
} {
  const [request, setRequest] = React.useState<ConfirmRequest | ReasonRequest | null>(null);
  const [open, setOpen] = React.useState(false);
  const [text, setText] = React.useState("");
  const textRef = React.useRef("");
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
      textRef.current = "";
      setText("");
      setRequest(next);
      setOpen(true);
    });
  }, []);

  const askReason = React.useCallback(
    async (next: ReasonRequest) => ((await askConfirm(next)) ? textRef.current.trim() : null),
    [askConfirm],
  );

  const field =
    request && "field" in request
      ? {
          ...request.field,
          value: text,
          onChange: (value: string) => {
            textRef.current = value;
            setText(value);
          },
        }
      : undefined;

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
      field={field}
      onConfirm={() => settle(true)}
    />
  ) : null;

  return { askConfirm, askReason, confirmDialog };
}
