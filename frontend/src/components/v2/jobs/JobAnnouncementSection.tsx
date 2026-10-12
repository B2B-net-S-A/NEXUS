"use client";

/**
 * Ogłoszenie rekrutacji: treść na portale, link aplikacyjny i portale (zakładka
 * „Zespół i ogłoszenie” Profilu Championa, 04.10.2026). Do 04.10.2026 była to
 * zakładka „Ogłoszenie” panelu bocznego obok Podglądu.
 */

import { Button } from "@/components/ui/button";
import { JobPortalsSection } from "@/components/v2/recruitment/JobPortalsSection";

export interface JobAnnouncementSectionProps {
  jobId: number;
  jobStatus: string | null | undefined;
  /** Brak = rola nie pisze ogłoszeń. */
  onWriteAnnouncement?: () => void;
  /** Brak = rola nie tworzy linku albo rekrutacja nie jest opublikowana. */
  onGenerateInviteLink?: () => void;
  /** Portale tylko do odczytu (rola bez edycji rekrutacji). */
  readOnly: boolean;
  /** Wejście z `/jobs/new` po nieudanej publikacji — portale od razu rozwinięte. */
  portalsFocus?: boolean;
}

export function JobAnnouncementSection({
  jobId,
  jobStatus,
  onWriteAnnouncement,
  onGenerateInviteLink,
  readOnly,
  portalsFocus = false,
}: JobAnnouncementSectionProps) {
  return (
    <div className="space-y-4" data-testid="job-announcement-section">
      <section className="space-y-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Ogłoszenie i link aplikacyjny
        </h3>
        {onWriteAnnouncement || onGenerateInviteLink ? (
          <div className="flex flex-wrap gap-2">
            {onWriteAnnouncement ? (
              <Button type="button" variant="outline" size="sm" onClick={onWriteAnnouncement}>
                Przygotuj ogłoszenie na portale
              </Button>
            ) : null}
            {onGenerateInviteLink ? (
              <Button type="button" variant="outline" size="sm" onClick={onGenerateInviteLink}>
                Wygeneruj link aplikacyjny
              </Button>
            ) : null}
          </div>
        ) : null}
        <p className="text-[12px] leading-snug text-muted-foreground">
          {onWriteAnnouncement
            ? "Treść na Pracuj.pl i JustJoin.IT układa się z Profilu Championa — bez nazwy klienta i stawek. "
            : ""}
          {onGenerateInviteLink
            ? "Kandydat z linku trafia od razu do „Nowych” tej rekrutacji."
            : jobStatus !== "published"
              ? "Link aplikacyjny da się wygenerować po opublikowaniu rekrutacji."
              : "Ogłoszenie i link przygotowuje osoba z zespołu rekrutacji."}
        </p>
      </section>
      <JobPortalsSection jobId={jobId} readOnly={readOnly} focusOnReady={portalsFocus} />
    </div>
  );
}
