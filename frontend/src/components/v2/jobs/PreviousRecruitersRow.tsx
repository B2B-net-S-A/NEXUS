"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";

import { apiErrorMessage } from "@/lib/api-error";
import { shortenPersonName } from "@/lib/job-header-subtitle";
import {
  dismissPreviousRecruiter,
  type PreviousRecruiter,
} from "@/lib/job-team";
import { invalidateJobTeam } from "@/lib/job-team-cache";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";

interface PreviousRecruitersRowProps {
  jobId: number;
  people: readonly PreviousRecruiter[];
  /** Rola przydzielająca (`can_staff`) — tylko ona usuwa z poprzednich. */
  canStaff: boolean;
  /** Zamknięta rekrutacja: wracają przy ponownym otwarciu na P1. */
  closed: boolean;
}

/** „14.10” — dzień przeniesienia w czasie firmy. */
function dayMonth(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    timeZone: "Europe/Warsaw",
  });
}

function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/**
 * Wiersz „Poprzedni rekruter” w panelu „Zespół” (14.10.2026, makieta 3).
 *
 * Osoby, które pracowały, aż rekrutacja zeszła z P1 albo została zamknięta.
 * Nie pracują (nie ma ich w „Moich”, w obłożeniu ani w dzwonkach
 * rekrutacji) i wracają same przy P1. „Usuń z poprzednich” = osoba schodzi
 * z zespołu jak przy „Zdejmij” i nie wróci; historia zostaje.
 */
export function PreviousRecruitersRow({
  jobId,
  people,
  canStaff,
  closed,
}: PreviousRecruitersRowProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [pending, setPending] = useState<number | null>(null);

  if (people.length === 0) return null;

  const dismiss = async (person: PreviousRecruiter) => {
    if (pending != null) return;
    const confirmed = await askConfirm({
      title: `Usunąć ${person.name} z poprzednich?`,
      description:
        "Ta osoba zejdzie z zespołu rekrutacji i nie wróci, gdy rekrutacja wróci na P1. Historia zostaje.",
      confirmLabel: "Usuń z poprzednich",
    });
    if (!confirmed) return;
    setPending(person.user_id);
    try {
      await dismissPreviousRecruiter(jobId, person.user_id);
      toast.showSuccess(`${person.name}: nie wróci przy P1.`);
    } catch (err) {
      toast.showError(
        apiErrorMessage(err, "Nie udało się usunąć osoby z poprzednich."),
      );
    } finally {
      invalidateJobTeam(queryClient, jobId);
      setPending(null);
    }
  };

  const returns = closed ? "wróci przy otwarciu na P1" : "wróci przy P1";
  const latest = people[people.length - 1];
  const mover = shortenPersonName(latest.parked_by_name);
  const why = latest.reason === "closed" ? "zamknięcie rekrutacji" : "zejście z P1";

  return (
    <div className="min-w-0 space-y-2" data-testid="job-previous-recruiters">
      <ul className="space-y-2" aria-label="Poprzedni rekruter">
        {people.map((person) => {
          const day = dayMonth(person.parked_at);
          return (
            <li key={person.user_id} className="flex items-start gap-1.5">
              <div className="min-w-0 flex-1">
                <span className="inline-flex min-w-0 items-center gap-2 text-sm text-muted-foreground">
                  <span
                    aria-hidden="true"
                    className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-muted text-[10px] font-semibold text-muted-foreground"
                  >
                    {initialsOf(person.name)}
                  </span>
                  <span className="truncate">{person.name}</span>
                </span>
                <p className="pl-8 text-[11px] leading-snug text-muted-foreground">
                  {day ? `do ${day} · ` : ""}
                  {person.will_return
                    ? returns
                    : "nie wróci — konto nieaktywne albo bez roli rekrutera"}
                </p>
              </div>
              {canStaff ? (
                <button
                  type="button"
                  className="hit-area inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:pointer-events-none disabled:opacity-50"
                  aria-label={`Usuń z poprzednich: ${person.name}`}
                  title="Usuń z poprzednich"
                  disabled={pending != null}
                  onClick={() => void dismiss(person)}
                >
                  <X className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              ) : null}
            </li>
          );
        })}
      </ul>
      <p className="text-[11px] leading-snug text-muted-foreground">
        {mover ? `Przesunął(a) ${mover} — ${why}. ` : `Powód: ${why}. `}
        {canStaff ? "Osoba usunięta z tej listy nie wróci." : null}
      </p>
      {confirmDialog}
    </div>
  );
}
