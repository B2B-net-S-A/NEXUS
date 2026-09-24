"use client";

/**
 * „Anuluj zamówienie” (MD / kosztowe). Anulowane zamówienie zostaje
 * w rejestrze razem z historią i da się je przywrócić do stanu sprzed
 * anulowania. Serwer odmawia (409), gdy zamówienie ma rozliczenia — wtedy
 * pokazujemy ich listę tutaj, w oknie, a nie w znikającym toaście.
 */

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { AppModal } from "@/components/ds";
import { Button } from "@/components/ui/button";
import type { OrderGroupRead } from "@/lib/api/orderGroups";

interface Props {
  group: OrderGroupRead | null;
  pending: boolean;
  /** Komunikat odmowy z serwera (np. lista rozliczeń). */
  error: string | null;
  onConfirm: (reason: string | null) => void;
  onClose: () => void;
}

/** Tekst odmowy anulowania z odpowiedzi 409 (`detail.message`) albo `null`. */
export function cancelRefusalMessage(error: unknown): string | null {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } } | null)
    ?.response;
  if (response?.status !== 409) return null;
  const detail = response.data?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    const message = (detail as { message?: unknown }).message;
    return typeof message === "string" ? message : null;
  }
  return null;
}

export function CancelOrderGroupDialog({ group, pending, error, onConfirm, onClose }: Props) {
  const [reason, setReason] = useState("");
  if (!group) return null;
  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={`Anulować zamówienie nr ${group.order_number}?`}
      description="Zamówienie i jego konsultanci dostaną status „Anulowane”. Historia zostaje, a „Przywróć anulowane” odtworzy stan sprzed anulowania. Zamówienia z rozliczeniami (zaraportowane MD, faktury) nie da się anulować — takie się kończy."
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={pending}>
            Nie anuluj
          </Button>
          <Button
            variant="primary"
            disabled={pending}
            onClick={() => onConfirm(reason.trim() || null)}
          >
            {pending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Anuluj zamówienie
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <label className="block space-y-1 text-sm">
          <span className="font-medium">Powód (opcjonalnie)</span>
          <textarea
            value={reason}
            maxLength={1000}
            onChange={(event) => setReason(event.target.value)}
            rows={3}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            placeholder="np. klient wycofał zamówienie przed startem"
          />
        </label>
        {error ? (
          <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}
