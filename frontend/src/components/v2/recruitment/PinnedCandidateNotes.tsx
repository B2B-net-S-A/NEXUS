"use client";

/**
 * Przypięte notatki kandydata (0399) — w doku osoby w rekrutacji, niezależnie
 * od rekrutacji, do której notatka należy. Przypięcie jest wspólne dla
 * zespołu („nie dzwonić przed 10”, „nie chce przejść na UoP”), więc ma być
 * widać je tam, gdzie rekruter pracuje z osobą, bez otwierania profilu.
 *
 * Nic przypiętego = nic nie rysujemy. Awaria to jedno zdanie z „Ponów” —
 * nie może wyglądać jak brak przypiętych notatek.
 */

import { useQuery } from "@tanstack/react-query";
import { Pin } from "lucide-react";

import api from "@/lib/api";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { formatDate } from "@/lib/utils";

interface PinnedNote {
  id: number;
  content: string;
  content_rendered?: string | null;
  author_name?: string | null;
  created_at: string;
  job_title?: string | null;
}

/** Klucz pod kluczem notatek kandydata — każde odświeżenie notatek go łapie. */
export const pinnedNotesQueryKey = (candidateId: number) =>
  [...candidateQueryKeys.notes(candidateId), "pinned"] as const;

export function PinnedCandidateNotes({ candidateId }: { candidateId: number }) {
  const query = useQuery<{ items?: PinnedNote[] }>({
    queryKey: pinnedNotesQueryKey(candidateId),
    queryFn: ({ signal }) =>
      api
        .get(`/api/notes?candidate_id=${candidateId}&pinned_only=true`, { signal })
        .then((r) => r.data),
    enabled: candidateId > 0,
    staleTime: 30_000,
  });

  if (query.isError) {
    return (
      <p role="alert" className="text-xs text-destructive-muted-foreground">
        Nie udało się sprawdzić przypiętych notatek.{" "}
        <button
          type="button"
          className="font-medium underline underline-offset-2"
          onClick={() => void query.refetch()}
        >
          Ponów
        </button>
      </p>
    );
  }
  const items = query.data?.items ?? [];
  if (items.length === 0) return null;

  return (
    <section aria-label="Przypięte notatki" className="space-y-1.5">
      {items.map((note) => (
        <div
          key={note.id}
          className="flex gap-2 rounded-lg border border-primary/40 bg-primary/5 px-2.5 py-2 text-xs"
        >
          <Pin className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" aria-label="Przypięta" />
          <div className="min-w-0">
            <p className="line-clamp-3 whitespace-pre-line text-foreground">
              {note.content_rendered ?? note.content}
            </p>
            <p className="mt-0.5 text-muted-foreground">
              {note.author_name ?? "Nieznany autor"} · {formatDate(note.created_at)}
              {note.job_title ? ` · ${note.job_title}` : ""}
            </p>
          </div>
        </div>
      ))}
    </section>
  );
}
