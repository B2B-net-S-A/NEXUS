"use client";

import { AppModal } from "@/components/ds/AppModal";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import type { AnnouncementRecipient, RecipientStatus } from "@/lib/api/care-announcements";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { recipientStatusLabel } from "./announcement-format";

const TONE: Record<RecipientStatus, StatusDotTone> = {
  pending: "info",
  sending: "info",
  sent: "success",
  failed: "danger",
  uncertain: "warning",
  bounced: "danger",
  excluded_no_email: "neutral",
  excluded_opted_out: "neutral",
  cancelled: "neutral",
};

interface RecipientsDialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  rows: AnnouncementRecipient[];
}

/** „Pokaż listę” — kto dostanie (albo dostał) komunikat i kto jest wykluczony. */
export function RecipientsDialog({ open, onClose, title, rows }: RecipientsDialogProps) {
  return (
    <AppModal
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      size="lg"
      title={title}
      description="Każdy dostaje osobny mail — nikt nie widzi innych adresów."
      footer={
        <Button variant="ghost" onClick={onClose}>
          Zamknij
        </Button>
      }
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className={CALM_ROW}>
              <th className={cn(CALM_HEAD, "sticky left-0 bg-background px-2 py-1.5 text-left")}>
                Osoba
              </th>
              <th className={cn(CALM_HEAD, "px-2 py-1.5 text-left")}>E-mail</th>
              <th className={cn(CALM_HEAD, "px-2 py-1.5 text-left")}>Opiekun</th>
              <th className={cn(CALM_HEAD, "px-2 py-1.5 text-left")}>Stan</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.candidate_id} className={CALM_ROW}>
                <td className="sticky left-0 bg-background px-2 py-1.5">
                  <span className="font-medium">{row.name}</span>
                  {row.client_name ? <span className={CALM_SUBLINE}>{row.client_name}</span> : null}
                </td>
                <td className="px-2 py-1.5">
                  {row.email ?? <span className={CALM_EMPTY}>—</span>}
                </td>
                <td className="px-2 py-1.5">
                  {row.owner_name ?? <span className={CALM_EMPTY}>—</span>}
                </td>
                <td className="px-2 py-1.5">
                  <StatusDot
                    tone={TONE[row.status]}
                    note={row.unsubscribed ? "wypisał się po tym komunikacie" : undefined}
                  >
                    {recipientStatusLabel(row.status)}
                  </StatusDot>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 ? (
          <p className="py-3 text-sm text-muted-foreground">Nikogo w tej grupie.</p>
        ) : null}
      </div>
    </AppModal>
  );
}
