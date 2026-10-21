"use client";

/**
 * Ogłoszenie rekrutacji: treść na portale, link aplikacyjny i portale (zakładka
 * „Zespół i ogłoszenie” Profilu Championa, 04.10.2026). Do 04.10.2026 była to
 * zakładka „Ogłoszenie” panelu bocznego obok Podglądu.
 *
 * Od 13.10.2026 pokazuje też, gdzie ogłoszenie wisi (`AdPublications`): stan
 * czyta z tego samego zapytania co okno „Ogłoszenie na portale”, więc harness
 * `/preview/champion-workspace` zasiewa `jobAdQueryKey`.
 */

import { Button } from "@/components/ui/button";
import { AdPublications } from "@/components/v2/job-ad/AdPublications";
import { JobPortalsSection } from "@/components/v2/recruitment/JobPortalsSection";
import { useJobAd } from "@/lib/api/jobAd";

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
  // Stan ogłoszeń widzi ta sama rola, która je przygotowuje.
  const ad = useJobAd(jobId, !!onWriteAnnouncement);
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
                Ogłoszenie — strona kariery i portale
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
            ? "Jedna treść z Profilu Championa: strona kariery jednym kliknięciem, Pracuj.pl i JustJoin.IT do wklejenia — bez nazwy klienta i stawek. "
            : ""}
          {onGenerateInviteLink
            ? "Kandydat z linku trafia od razu do „Nowych” tej rekrutacji."
            : jobStatus !== "published"
              ? "Link aplikacyjny da się wygenerować po opublikowaniu rekrutacji."
              : "Ogłoszenie i link przygotowuje osoba z zespołu rekrutacji."}
        </p>
        {onWriteAnnouncement && ad.isSuccess ? (
          <AdPublications
            jobId={jobId}
            portals={["pracuj", "jjit"]}
            state={ad.data}
            jobClosed={jobStatus === "closed"}
          />
        ) : null}
        {onWriteAnnouncement && ad.isError ? (
          <p className="text-[12px] text-destructive">
            Nie udało się wczytać, gdzie ogłoszenie jest opublikowane. Odśwież stronę.
          </p>
        ) : null}
      </section>
      <JobPortalsSection jobId={jobId} readOnly={readOnly} focusOnReady={portalsFocus} />
    </div>
  );
}
