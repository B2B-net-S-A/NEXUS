"use client";

/**
 * Karta akcji Jarvisa — jedyna droga do zapisu.
 *
 * Tekst karty buduje SERWER z zapisanych argumentów (nazwy doczytane przez
 * API), nie model. „Zrób to” wykonuje dokładnie to, co widać na karcie.
 * Zapis łatwy do cofnięcia (27.10.2026) przychodzi już wykonany — wtedy
 * karta ma „Cofnij” przez 15 minut.
 */

import { AlertTriangle, Check, Clock, Loader2, Undo2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { JarvisAction } from "@/lib/jarvis/types";
import { JarvisMarkdown } from "./JarvisMarkdown";

interface Props {
  action: JarvisAction;
  busy?: boolean;
  disabled?: boolean;
  onConfirm?: (action: JarvisAction) => void;
  onReject?: (action: JarvisAction) => void;
  onUndo?: (action: JarvisAction) => void;
}

const UNDO_LINE = {
  running: { icon: Loader2, text: "Cofam…", tone: "text-muted-foreground" },
  done: { icon: Undo2, text: "Cofnięte — zmiana usunięta", tone: "text-muted-foreground" },
  failed: { icon: AlertTriangle, text: "Nie udało się cofnąć — sprawdź na ekranie", tone: "text-destructive" },
} as const;

function canUndo(action: JarvisAction): boolean {
  const undo = action.undo;
  if (!undo || undo.state !== "available") return false;
  return !undo.until || new Date(undo.until).getTime() > Date.now();
}

const STATUS_LINE: Record<Exclude<JarvisAction["status"], "proposed">, { icon: typeof Check; text: string; tone: string }> = {
  confirmed: { icon: Loader2, text: "Wykonuję…", tone: "text-muted-foreground" },
  executed: { icon: Check, text: "Wykonane", tone: "text-success" },
  rejected: { icon: X, text: "Anulowane — nic nie zmieniono", tone: "text-muted-foreground" },
  failed: { icon: AlertTriangle, text: "Nie udało się", tone: "text-destructive" },
  expired: { icon: Clock, text: "Propozycja wygasła — poproś o nową", tone: "text-muted-foreground" },
};

const UNCERTAIN_LINE = {
  icon: AlertTriangle,
  text: "Przerwane w trakcie — nie wiadomo, czy się zapisało. Sprawdź na ekranie.",
  tone: "text-warning",
};

export function JarvisActionCard({ action, busy = false, disabled = false, onConfirm, onReject, onUndo }: Props) {
  const pending = action.status === "proposed";
  const undoState = action.undo?.state;
  const undoLine = undoState === "running" || undoState === "done" || undoState === "failed" ? UNDO_LINE[undoState] : null;
  // Przerwane w trakcie (restart, zerwane połączenie) to NIE „nie udało się”:
  // zmiana mogła się zapisać — karta mówi to wprost (runda 8, R8-N1-5).
  const uncertain = action.status === "failed" && action.result?.uncertain === true;
  const status = action.status === "proposed" ? null : uncertain ? UNCERTAIN_LINE : STATUS_LINE[action.status];
  const error = action.status === "failed" && !uncertain ? action.result?.error : undefined;
  return (
    <div
      className="rounded-lg border border-primary/30 bg-card p-3 shadow-xs"
      data-testid="jarvis-action-card"
      data-status={action.status}
    >
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-primary">
        {pending ? "Do zatwierdzenia" : action.undo ? "Zrobione za Ciebie" : "Akcja"}
      </div>
      <JarvisMarkdown>{action.preview.text}</JarvisMarkdown>
      {action.preview.body && (
        // Pełna treść zapisu, dokładnie ta, którą „Zrób to” zapisze — jako
        // zwykły tekst (NIE markdown: to treść pochodząca od modelu).
        <pre
          className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/50 px-2 py-1.5 font-sans text-xs text-foreground"
          data-testid="jarvis-action-body"
        >
          {action.preview.body}
        </pre>
      )}
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
      ) : undoLine ? (
        <p className={`mt-2 flex items-center gap-1.5 text-xs font-medium ${undoLine.tone}`}>
          <undoLine.icon className={`h-3.5 w-3.5 ${undoState === "running" ? "animate-spin" : ""}`} aria-hidden />
          {undoLine.text}
        </p>
      ) : (
        status && (
          <div className="mt-2 flex items-center justify-between gap-2">
            <p className={`flex items-center gap-1.5 text-xs font-medium ${status.tone}`}>
              <status.icon className={`h-3.5 w-3.5 ${action.status === "confirmed" ? "animate-spin" : ""}`} aria-hidden />
              {error ? `${status.text}: ${error}` : status.text}
            </p>
            {canUndo(action) && onUndo && (
              <Button size="sm" variant="ghost" loading={busy} disabled={disabled || busy} onClick={() => onUndo(action)}>
                <Undo2 className="mr-1 h-3.5 w-3.5" aria-hidden />
                Cofnij
              </Button>
            )}
          </div>
        )
      )}
    </div>
  );
}
