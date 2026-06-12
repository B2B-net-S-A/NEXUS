"use client";

import { Clock, PhoneCall, PhoneIncoming, User } from "lucide-react";

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { dialerApi, type Call } from "@/lib/api";
import AudioPlayer from "./AudioPlayer";

interface CallDetailsDialogProps {
  call: Call | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pl-PL", {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

export default function CallDetailsDialog({
  call,
  open,
  onOpenChange,
}: CallDetailsDialogProps) {
  if (!call) return null;

  const DirectionIcon =
    call.direction === "outbound" ? PhoneCall : PhoneIncoming;

  // Dialer recordings live in our storage → authed proxy. Legacy CloudTalk
  // recordings are public/signed URLs.
  const isDialer = call.provider_type === "dialer";
  const hasRecording = isDialer
    ? Boolean(call.recording_storage_key)
    : Boolean(call.recording_url);
  const recordingSrc = isDialer
    ? dialerApi.recordingUrl(call.id)
    : (call.recording_url ?? "");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>
            <div className="flex items-center gap-2">
              <DirectionIcon className="h-5 w-5 text-primary" />
              {call.direction === "outbound" ? "Rozmowa wychodząca" : "Rozmowa przychodząca"}
            </div>
          </DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-muted-foreground">
                <Clock className="h-3.5 w-3.5" />
                <span className="text-xs">Rozpoczęta</span>
              </div>
              <div className="text-foreground font-medium">
                {formatDateTime(call.started_at || call.created_at)}
              </div>
            </div>
            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-muted-foreground">
                <Clock className="h-3.5 w-3.5" />
                <span className="text-xs">Czas trwania</span>
              </div>
              <div className="text-foreground font-medium">
                {formatDuration(call.duration_seconds)}
              </div>
            </div>
            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-muted-foreground">
                <User className="h-3.5 w-3.5" />
                <span className="text-xs">Agent</span>
              </div>
              <div className="text-foreground font-medium">
                {call.cloudtalk_agent_id ?? "—"}
              </div>
            </div>
            <div className="space-y-1">
              <div className="text-xs text-muted-foreground">Status</div>
              <div className="text-foreground font-medium capitalize">
                {call.status}
              </div>
            </div>
          </div>

          {hasRecording && (
            <div className="space-y-1.5">
              <div className="text-xs font-medium text-muted-foreground">
                Nagranie
              </div>
              <AudioPlayer src={recordingSrc} authed={isDialer} />
            </div>
          )}

          {call.summary && (
            <div className="space-y-1.5">
              <div className="text-xs font-medium text-muted-foreground">
                Podsumowanie
              </div>
              <p className="text-sm text-foreground whitespace-pre-line">
                {call.summary}
              </p>
            </div>
          )}

          {call.transcript && (
            <details className="rounded-md border border-border">
              <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-foreground hover:bg-accent/40">
                Transkrypt
              </summary>
              <div className="px-3 py-2 text-sm text-foreground whitespace-pre-line border-t border-border bg-card/60 max-h-72 overflow-y-auto">
                {call.transcript}
              </div>
            </details>
          )}

          {!call.summary && !call.transcript && !hasRecording && (
            <p className="text-sm text-muted-foreground italic">
              Brak transkryptu, podsumowania ani nagrania dla tej rozmowy.
            </p>
          )}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
