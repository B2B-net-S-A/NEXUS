"use client";

import { useState } from "react";
import { Mic, PhoneCall, PhoneIncoming, PhoneMissed, PhoneOff } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { Call } from "@/lib/api";
import CallDetailsDialog from "./CallDetailsDialog";

interface CallsTimelineProps {
  calls: Call[];
}

function formatDuration(seconds: number | null): string | null {
  if (seconds == null) return null;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function formatRelative(iso: string | null): string {
  if (!iso) return "";
  try {
    const date = new Date(iso);
    const diffSec = Math.floor((Date.now() - date.getTime()) / 1000);
    if (diffSec < 60) return "przed chwilą";
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)} min temu`;
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)} godz. temu`;
    if (diffSec < 86400 * 30) return `${Math.floor(diffSec / 86400)} dni temu`;
    return date.toLocaleDateString("pl-PL");
  } catch {
    return iso;
  }
}

function DirectionIcon({ call }: { call: Call }) {
  if (call.status === "missed") {
    return <PhoneMissed className="h-3.5 w-3.5 text-red-500" />;
  }
  if (call.status === "failed") {
    return <PhoneOff className="h-3.5 w-3.5 text-amber-500" />;
  }
  if (call.direction === "inbound") {
    return <PhoneIncoming className="h-3.5 w-3.5 text-primary" />;
  }
  return <PhoneCall className="h-3.5 w-3.5 text-primary" />;
}

function CallRow({ call, onOpen }: { call: Call; onOpen: () => void }) {
  const dur = formatDuration(call.duration_seconds);
  const when = call.started_at || call.created_at;
  const directionLabel =
    call.direction === "outbound" ? "↗ Wychodząca" : "↙ Przychodząca";

  return (
    <button
      type="button"
      onClick={onOpen}
      className="w-full text-left rounded-lg border border-border p-3 hover:bg-accent/40 transition-colors"
    >
      <div className="flex items-center gap-2 flex-wrap">
        <DirectionIcon call={call} />
        <span className="text-sm font-medium text-foreground">
          {directionLabel}
        </span>
        {dur && (
          <Badge size="sm" variant="soft">
            {dur}
          </Badge>
        )}
        {call.status === "initiated" && (
          <Badge size="sm" variant="soft" className="bg-amber-500/10 text-amber-700">
            Trwa…
          </Badge>
        )}
        {call.transcript && (
          <Badge size="sm" variant="soft" className="gap-1">
            <Mic className="h-3 w-3" />
            Transkrypt
          </Badge>
        )}
        <span className="ml-auto text-xs text-muted-foreground">
          {formatRelative(when)}
        </span>
      </div>
      {call.summary && (
        <p className="text-sm text-foreground mt-2 line-clamp-2">
          {call.summary}
        </p>
      )}
    </button>
  );
}

/**
 * Replaces the legacy in-line ``RozmowyTab``. Renders the candidate's call
 * history; clicking a row opens :class:`CallDetailsDialog` with transcript +
 * audio player.
 */
export default function CallsTimeline({ calls }: CallsTimelineProps) {
  const [openCall, setOpenCall] = useState<Call | null>(null);

  if (!Array.isArray(calls) || calls.length === 0) {
    return (
      <div className="py-6 text-center text-sm text-muted-foreground">
        Brak zarejestrowanych rozmów.
      </div>
    );
  }

  return (
    <>
      <div className="space-y-2">
        {calls.map((c) => (
          <CallRow key={c.id} call={c} onOpen={() => setOpenCall(c)} />
        ))}
      </div>
      <CallDetailsDialog
        call={openCall}
        open={openCall !== null}
        onOpenChange={(o) => !o && setOpenCall(null)}
      />
    </>
  );
}
