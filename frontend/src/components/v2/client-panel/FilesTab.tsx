"use client";

import { Button } from "@/components/ui/button";
import type { PanelCandidate, PanelCandidateDetail } from "@/lib/api/clientPanel";
import { cn } from "@/lib/utils";

import { usePanelContext } from "./panel-context";
import { formatPanelDate } from "./panel-logic";
import { PANEL_CARD } from "./parts";

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1, dot + 5).toUpperCase() : "PLIK";
}

function FileRow({
  badge,
  name,
  note,
  href,
  onOpen,
}: {
  badge: string;
  name: string;
  note: string | null;
  href: string;
  onOpen?: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2.5 border-b border-border px-3 py-2 last:border-b-0">
      <span
        aria-hidden
        className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-muted text-[10px] font-bold text-muted-foreground"
      >
        {badge}
      </span>
      <div className="min-w-[180px] flex-1">
        <div className="break-words text-sm font-medium">{name}</div>
        {note ? <div className="text-xs text-muted-foreground">{note}</div> : null}
      </div>
      <Button asChild variant="outline" size="sm">
        <a href={href} target="_blank" rel="noopener noreferrer" onClick={onOpen}>
          Pobierz
        </a>
      </Button>
    </div>
  );
}

export function FilesTab({
  candidate,
  detail,
  allowActions,
  onAskForFile,
}: {
  candidate: PanelCandidate;
  detail: PanelCandidateDetail;
  allowActions: boolean;
  onAskForFile: () => void;
}) {
  const { transport } = usePanelContext();
  const { cv, files } = detail;

  return (
    <div className="overflow-auto">
      <div className={PANEL_CARD}>
        {cv.available && cv.url ? (
          <FileRow
            badge="PDF"
            name={cv.filename ?? "CV"}
            note={candidate.sent_at ? `CV przesłane ${formatPanelDate(candidate.sent_at)}` : null}
            href={transport.fileHref(cv.url)}
            onOpen={() =>
              transport.sendEvent({ public_id: candidate.public_id, action: "file", detail: "CV" })
            }
          />
        ) : (
          <div className={cn("border-b border-border px-3 py-2 text-sm text-muted-foreground")}>
            Pliku CV nie ma w panelu. Opiekun procesu prześle go ponownie na prośbę.
          </div>
        )}
        {files.map((file) => (
          <FileRow
            key={file.id}
            badge={file.kind === "certificate" ? "CERT" : extensionOf(file.name)}
            name={file.name}
            note={file.kind === "certificate" ? "Certyfikat dołączony przez kandydata" : null}
            href={transport.fileHref(file.url)}
          />
        ))}
        {files.length === 0 ? (
          <div className="px-3 py-2 text-sm text-muted-foreground">
            Kandydat nie dołączył certyfikatów.{" "}
            {allowActions ? (
              <button
                type="button"
                className="font-medium text-primary underline-offset-4 hover:underline"
                onClick={onAskForFile}
              >
                Poproś o dokument
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
