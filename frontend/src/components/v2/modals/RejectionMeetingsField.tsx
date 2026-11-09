"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CalendarX } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import { apiErrorMessage } from "@/lib/api-error";
import {
  fetchPairMeetings,
  meetingWhen,
  pairMeetingsKey,
  type PairMeeting,
  type PairMeetingsChoice,
} from "@/lib/api/pairMeetings";

/**
 * Spotkania przy zamknięciu karty (zgłoszenie 09.11.2026, decyzja Artura):
 * domyślnie do odwołania. Zamknięta para znika z Kalendarza razem z przyciskiem
 * „Odwołaj”, więc to ostatnie miejsce, w którym da się to zrobić odruchowo.
 */

const HINT: Record<PairMeeting["kind"], string> = {
  prep: "Kandydat dostanie odwołanie z kalendarza prowadzącego.",
  client_interview: "Zniknie z kalendarza NEXUSA. NEXUS nie powiadomi klienta, napisz do niego sam.",
  outlook: "Wysłane z Outlooka, NEXUS tego nie odwoła. Poprosimy prowadzącego dzwonkiem.",
};

export function choiceFrom(meetings: PairMeeting[], unchecked: number[]): PairMeetingsChoice {
  const picked = meetings.filter((m) => !unchecked.includes(m.event_id));
  return {
    cancel: picked.filter((m) => m.cancellable).map((m) => m.event_id),
    ask: picked.filter((m) => !m.cancellable).map((m) => m.event_id),
  };
}

export function RejectionMeetingsField({
  jobId,
  candidateId,
  onChange,
}: {
  jobId: number;
  candidateId: number;
  onChange: (choice: PairMeetingsChoice | null) => void;
}) {
  const query = useQuery({
    queryKey: pairMeetingsKey(jobId, candidateId),
    queryFn: () => fetchPairMeetings(jobId, candidateId),
    staleTime: 0,
    retry: false,
  });
  const [unchecked, setUnchecked] = useState<number[]>([]);
  const meetings = query.data;

  useEffect(() => setUnchecked([]), [jobId, candidateId]);
  useEffect(() => {
    onChange(meetings ? choiceFrom(meetings, unchecked) : null);
  }, [meetings, unchecked, onChange]);

  if (query.isError) {
    return (
      <p className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm" role="alert">
        {apiErrorMessage(
          query.error,
          "Nie udało się sprawdzić spotkań tej osoby. Po zamknięciu karty zajrzyj do Kalendarza.",
        )}
      </p>
    );
  }
  if (!query.isSuccess || query.data.length === 0) return null;
  return (
    <section
      className="space-y-2 rounded-lg border border-warning/40 bg-warning/10 p-3"
      data-testid="rejection-meetings"
    >
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <CalendarX className="h-4 w-4" aria-hidden="true" />
        Ta osoba ma zaplanowane spotkania
      </h3>
      <ul className="space-y-2">
        {query.data.map((meeting) => {
          const id = `meeting-${meeting.event_id}`;
          return (
            <li key={meeting.event_id} className="flex items-start gap-2">
              <Checkbox
                id={id}
                checked={!unchecked.includes(meeting.event_id)}
                onCheckedChange={(value) =>
                  setUnchecked((list) =>
                    value
                      ? list.filter((eventId) => eventId !== meeting.event_id)
                      : [...list, meeting.event_id],
                  )
                }
                className="mt-0.5"
              />
              <label htmlFor={id} className="min-w-0 text-sm">
                <span className="font-medium">
                  {meeting.cancellable ? "Odwołaj: " : "Poproś o odwołanie: "}
                </span>
                {[meeting.title, meetingWhen(meeting.start), meeting.host].filter(Boolean).join(" · ")}
                <span className="block text-xs text-muted-foreground">{HINT[meeting.kind]}</span>
              </label>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
