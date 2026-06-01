"use client";

import { useState } from "react";
import { Phone, Loader2 } from "lucide-react";

import { cloudtalkApi } from "@/lib/api";
import { useToast } from "@/components/Toast";

interface CallButtonProps {
  candidateId: number;
  phone: string | null;
  /**
   * Render as the existing contact-row anchor (text + icon inline) when
   * ``compact`` is true; full button with bg/border otherwise.
   */
  compact?: boolean;
  className?: string;
}

/**
 * Click-to-call trigger backed by `POST /api/cloudtalk/initiate-call`.
 *
 * The backend stubs a `Call(status=initiated)` row and CloudTalk rings the
 * user's softphone. When the call ends, the webhook UPDATEs the same row by
 * `cloudtalk_call_id` with duration/transcript/recording.
 *
 * Falls back to `tel:` link when phone is set but CloudTalk returns 412
 * (user not mapped to an agent) or 503 (kill-switch off) – the user can
 * still dial manually on mobile.
 */
export default function CallButton({
  candidateId,
  phone,
  compact = false,
  className = "",
}: CallButtonProps) {
  const { showSuccess, showError } = useToast();
  const [isLoading, setLoading] = useState(false);

  if (!phone) return null;

  const handleClick = async (e: React.MouseEvent) => {
    e.preventDefault();
    if (isLoading) return;
    setLoading(true);
    try {
      await cloudtalkApi.initiateCall(candidateId);
      showSuccess("Dzwonimy – odbierz swój softphone CloudTalk");
    } catch (err: unknown) {
      const status =
        (err as { response?: { status?: number } })?.response?.status;
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || "Nie udało się zadzwonić";
      if (status === 412) {
        showError(detail);
      } else if (status === 503) {
        showError("CloudTalk wyłączony – skontaktuj się z administratorem");
      } else {
        showError(detail);
      }
    } finally {
      setLoading(false);
    }
  };

  if (compact) {
    return (
      <button
        type="button"
        onClick={handleClick}
        disabled={isLoading}
        className={`inline-flex items-center gap-1.5 hover:text-primary disabled:opacity-50 ${className}`}
        title="Zadzwoń przez CloudTalk"
      >
        {isLoading ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
        ) : (
          <Phone className="h-3.5 w-3.5 text-muted-foreground" />
        )}
        {phone}
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={isLoading}
      className={`inline-flex items-center gap-2 rounded-md border border-border bg-background px-3 py-1.5 text-sm font-medium hover:bg-accent disabled:opacity-50 ${className}`}
    >
      {isLoading ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        <Phone className="h-4 w-4" />
      )}
      Zadzwoń
    </button>
  );
}
