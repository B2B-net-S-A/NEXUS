"use client";

/**
 * Karta akcji zaproponowanej przez Jarvisa — jedyna droga do zapisu.
 *
 * Tekst karty buduje SERWER z zapisanych argumentów (nazwy doczytane przez
 * API), nie model. „Zrób to” wykonuje dokładnie to, co widać na karcie.
 */

import { AlertTriangle, Check, Clock, Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { JarvisAction } from "@/lib/jarvis/types";
import { JarvisMarkdown } from "./JarvisMarkdown";

interface Props {
  action: JarvisAction;
  busy?: boolean;
  disabled?: boolean;
  onConfirm?: (action: JarvisAction) => void;
  onReject?: (action: JarvisAction) => void;
}

const STATUS_LINE: Record<Exclude<JarvisAction["status"], "proposed">, { icon: typeof Check; text: string; tone: string }> = {
  confirmed: { icon: Loader2, text: "Wykonuję…", tone: "text-muted-foreground" },
  executed: { icon: Check, text: "Wykonane", tone: "text-success" },
  rejected: { icon: X, text: "Anulowane — nic nie zmieniono", tone: "text-muted-foreground" },
  failed: { icon: AlertTriangle, text: "Nie udało się", tone: "text-destructive" },
  expired: { icon: Clock, text: "Propozycja wygasła — poproś o nową", tone: "text-muted-foreground" },
};

export function JarvisActionCard({ action, busy = false, disabled = false, onConfirm, onReject }: Props) {
  const pending = action.status === "proposed";
  const status = action.status === "proposed" ? null : STATUS_LINE[action.status];
  const error = action.status === "failed" ? action.result?.error : undefined;
  return (
    <div
      className="rounded-lg border border-primary/30 bg-card p-3 shadow-xs"
      data-testid="jarvis-action-card"
      data-status={action.status}
    >
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-primary">
        {pending ? "Do zatwierdzenia" : "Akcja"}
      </div>
      <JarvisMarkdown>{action.preview.text}</JarvisMarkdown>
      {action.preview.warning && pending && (
        <p className="mt-2 flex items-start gap-1.5 rounded-md bg-warning-muted px-2 py-1.5 text-xs text-warning-muted-foreground">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          {action.preview.warning}
        </p>
      )}
      {pending ? (
        <div className="mt-3 flex gap-2">
          <Button size="sm" loading={busy} disabled={disabled || busy} onClick={() => onConfirm?.(action)}>
            Zrób to
          </Button>
          <Button size="sm" variant="ghost" disabled={disabled || busy} onClick={() => onReject?.(action)}>
            Anuluj
          </Button>
        </div>
      ) : (
        status && (
          <p className={`mt-2 flex items-center gap-1.5 text-xs font-medium ${status.tone}`}>
            <status.icon className={`h-3.5 w-3.5 ${action.status === "confirmed" ? "animate-spin" : ""}`} aria-hidden />
            {error ? `${status.text}: ${error}` : status.text}
          </p>
        )
      )}
    </div>
  );
}
