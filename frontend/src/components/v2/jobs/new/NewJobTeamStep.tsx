"use client";

/**
 * `/jobs/new` → „Rekruter i priorytet” (decyzje Artura 02.10.2026).
 *
 * Kto dostanie rekrutację po przekazaniu do searchu i jak jest pilna. Domyślnie
 * osobę proponuje automat (zatwierdza Head of Recruitment), a „Wybieram sam”
 * przypisuje wskazane osoby od razu. Do 02.10 te pola stały w przyklejonej
 * stopce strony — z priorytetem i opisem opcji zajęłyby na laptopie jedną
 * trzecią okna, więc dostały własną sekcję, a w stopce zostały przyciski.
 *
 * Nic się tu nie zapisuje: rekruter idzie w `POST …/handoff`, kolejne osoby
 * w `POST …/collaborators`, priorytet w `POST /api/jobs`.
 */

import { useId } from "react";
import { Users } from "lucide-react";

import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { JobCollaboratorsField } from "@/components/jobs/JobCollaboratorsField";
import { RecruiterAssignmentChoice } from "@/components/v2/jobs/RecruiterAssignmentChoice";
import {
  AUTOMATIC_DISABLED_TEXT,
  type AllocationMode,
  type RecruiterAssignment,
} from "@/lib/recruiter-assignment";
import {
  PRIORITY_LEVEL_OPTIONS,
  type PriorityLevel,
} from "@/lib/request-priority";

export interface RecruiterOption {
  id: number;
  name?: string | null;
  email?: string | null;
}

interface Props {
  /** Wybór obowiązujący (`resolveRecruiterAssignment`). */
  assignment: RecruiterAssignment;
  onAssignmentChange: (value: RecruiterAssignment) => void;
  automaticAvailable: boolean;
  /** Odczyt się udał i automat jest wyłączony — pod polem stoi powód. */
  automaticOff: boolean;
  mode: AllocationMode | undefined;
  recruiters: RecruiterOption[];
  /** Lista rekruterów się nie wczytała (i nie ma jej w pamięci podręcznej). */
  recruitersFailed: boolean;
  onRecruitersRetry: () => void;
  recruiterId: number | null;
  onRecruiterChange: (id: number | null) => void;
  collaboratorIds: number[];
  onCollaboratorsChange: (ids: number[]) => void;
  priorityLevel: PriorityLevel;
  onPriorityChange: (level: PriorityLevel) => void;
  disabled?: boolean;
}

export function NewJobTeamStep({
  assignment,
  onAssignmentChange,
  automaticAvailable,
  automaticOff,
  mode,
  recruiters,
  recruitersFailed,
  onRecruitersRetry,
  recruiterId,
  onRecruiterChange,
  collaboratorIds,
  onCollaboratorsChange,
  priorityLevel,
  onPriorityChange,
  disabled = false,
}: Props) {
  const id = useId();
  const automatic = assignment === "automatic";

  return (
    <section
      aria-labelledby={`${id}-title`}
      className="flex flex-col gap-4 rounded-xl border border-border bg-card p-4 sm:p-5"
    >
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Users className="h-4 w-4" aria-hidden />
        </span>
        <div>
          <h2 id={`${id}-title`} className="text-sm font-semibold text-foreground">
            Rekruter i priorytet
          </h2>
          <p className="text-xs text-muted-foreground">
            Kto dostanie rekrutację po przekazaniu do searchu i jak jest pilna.
          </p>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <span id={`${id}-recruiter`} className="text-sm font-medium text-foreground">
          Rekruter
        </span>
        <RecruiterAssignmentChoice
          labelledBy={`${id}-recruiter`}
          value={assignment}
          onChange={onAssignmentChange}
          automaticAvailable={automaticAvailable}
          unavailableReason={automaticOff ? AUTOMATIC_DISABLED_TEXT : null}
          mode={mode}
          passive={priorityLevel === "accepting"}
          disabled={disabled}
        />
        {!automatic && (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="flex min-w-0 flex-col gap-1">
                <select
                  aria-label="Wybierz rekrutera"
                  className="h-10 w-full min-w-0 rounded-lg border border-border bg-card px-3 text-sm text-foreground"
                  value={recruiterId ?? ""}
                  disabled={disabled}
                  onChange={(e) =>
                    onRecruiterChange(e.target.value ? Number(e.target.value) : null)
                  }
                >
                  <option value="">Wybierz rekrutera…</option>
                  {recruiters.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name || r.email || `#${r.id}`}
                    </option>
                  ))}
                </select>
                {/* Runda 8 (R8-N14-6): pusta lista przy awarii blokowała
                    przekazanie bez słowa wyjaśnienia. */}
                {recruitersFailed ? (
                  <span role="alert" className="text-xs text-destructive">
                    Nie udało się wczytać listy rekruterów.{" "}
                    <button
                      type="button"
                      className="font-medium underline"
                      onClick={onRecruitersRetry}
                    >
                      Ponów
                    </button>
                  </span>
                ) : null}
              </div>
              {/* Decyzja 29.09.2026: nad rekrutacją może pracować kilka osób —
                  dopisywane po utworzeniu rekrutacji. */}
              <div className="flex min-w-0 flex-col gap-1">
                <span className="text-xs font-medium text-muted-foreground">
                  Kolejne osoby
                </span>
                <JobCollaboratorsField
                  value={collaboratorIds}
                  onChange={onCollaboratorsChange}
                  primaryOwnerId={recruiterId}
                />
              </div>
            </div>
            <p className="text-xs leading-snug text-muted-foreground">
              Wskazane osoby są przypisane od razu, bez akceptacji.
            </p>
          </>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <span id={`${id}-priority`} className="text-sm font-medium text-foreground">
          Priorytet
        </span>
        <SegmentedRadio<PriorityLevel>
          labelledBy={`${id}-priority`}
          // Kolumna flex rozciąga dzieci — przełącznik ma mieć szerokość opcji.
          className="self-start"
          value={priorityLevel}
          onChange={onPriorityChange}
          options={PRIORITY_LEVEL_OPTIONS}
          disabled={disabled}
        />
        <p className="text-xs leading-snug text-muted-foreground">
          Nowa rekrutacja zaczyna od P2. P1 idzie pierwsze w kolejce automatu;
          „Przyjmujemy kandydatów” znaczy, że nie szukamy aktywnie.
        </p>
      </div>
    </section>
  );
}
