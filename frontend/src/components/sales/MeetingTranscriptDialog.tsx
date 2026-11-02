"use client";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useMeetingTranscript } from "@/lib/api/sales";
import { resolveViewState } from "@/lib/view-state";

interface MeetingTranscriptDialogProps {
  activityId: number;
  onClose: () => void;
}

/** Podsumowanie i pełny transkrypt Teams spotkania handlowca. */
export function MeetingTranscriptDialog({ activityId, onClose }: MeetingTranscriptDialogProps) {
  const transcript = useMeetingTranscript(activityId);
  const state = resolveViewState({
    isLoading: transcript.isLoading,
    error: transcript.error,
    isSuccess: transcript.isSuccess,
    isEmpty: false,
  });
  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={transcript.data?.subject ?? "Transkrypt spotkania"}
    >
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie transkryptu…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void transcript.refetch()} />
      ) : (
        <div className="space-y-3">
          {transcript.data?.summary && (
            <div className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm">
              <p className="font-medium text-foreground">Podsumowanie</p>
              <p className="whitespace-pre-line text-muted-foreground">{transcript.data.summary}</p>
            </div>
          )}
          <p className="max-h-[50dvh] overflow-y-auto whitespace-pre-line text-sm text-foreground">
            {transcript.data?.plain_text}
          </p>
        </div>
      )}
    </AppModal>
  );
}
