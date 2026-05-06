"use client";

/**
 * Sources Panel — Phase 14 (Fireflies enrichment).
 *
 * Sits next to the ChampionProfileEditor on the Job detail view. Shows:
 *   1. Pending AI suggestions for this Job (each can be reviewed in the modal)
 *   2. Meetings (Fireflies transcripts) already attached to this Job
 *   3. Unlinked recent meetings — DL can manually attach any of them, which
 *      triggers a fresh enrichment suggestion.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, Loader2, Sparkles } from "lucide-react";
import { api, championSuggestionsApi } from "@/lib/api";
import type { ChampionProfile, ChampionProfileSuggestion } from "@/lib/api";
import { ChampionHistoricalMatchesPanel } from "./ChampionHistoricalMatchesPanel";
import { ChampionProfileSuggestionReview } from "./ChampionProfileSuggestionReview";

interface NoteItem {
  id: number;
  note_type: string;
  content: string;
  job_id: number | null;
  candidate_id: number | null;
  created_at: string;
}

interface NoteListResponse {
  items: NoteItem[];
  total: number;
}

interface ChampionProfileSourcesPanelProps {
  jobId: number;
  currentProfile: ChampionProfile;
  /** Phase 15: scope Qdrant retrieval to this client's closed jobs.
   *  `null` means "no client" — panel falls back to cross-client mode. */
  clientId?: number | null;
}

function noteTitle(content: string): string {
  const firstLine = (content || "").split("\n", 1)[0] || "";
  return firstLine.replace(/^#\s*/, "").trim() || "(bez tytułu)";
}

export function ChampionProfileSourcesPanel({
  jobId,
  currentProfile,
  clientId,
}: ChampionProfileSourcesPanelProps) {
  const qc = useQueryClient();
  const [activeSuggestion, setActiveSuggestion] =
    useState<ChampionProfileSuggestion | null>(null);
  // Phase 15: default same-client; user can flip to cross-client inside panel.
  const [historicalCrossClient, setHistoricalCrossClient] = useState(
    clientId == null,
  );

  const pending = useQuery({
    queryKey: ["champion-suggestions", jobId],
    queryFn: async () => {
      const res = await championSuggestionsApi.list(jobId, "pending");
      return res.data;
    },
  });

  const attached = useQuery<NoteListResponse>({
    queryKey: ["notes-attached", jobId],
    queryFn: async () => {
      const res = await api.get<NoteListResponse>(
        `/api/notes?job_id=${jobId}`,
      );
      return res.data;
    },
  });

  const unlinked = useQuery<NoteListResponse>({
    queryKey: ["notes-unlinked"],
    queryFn: async () => {
      const res = await api.get<NoteListResponse>(`/api/notes`);
      return res.data;
    },
  });

  const unlinkedMeetings = useMemo(() => {
    const items = unlinked.data?.items ?? [];
    return items.filter(
      (n) => n.note_type === "meeting" && (n.job_id == null || n.job_id === undefined),
    );
  }, [unlinked.data]);

  const linkMutation = useMutation({
    mutationFn: async (noteId: number) => {
      const res = await api.post(`/api/notes/${noteId}/link-job`, {
        job_id: jobId,
      });
      return res.data as {
        note_id: number;
        job_id: number;
        suggestion: ChampionProfileSuggestion;
      };
    },
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["champion-suggestions", jobId] });
      qc.invalidateQueries({ queryKey: ["notes-attached", jobId] });
      qc.invalidateQueries({ queryKey: ["notes-unlinked"] });
      setActiveSuggestion(result.suggestion);
    },
  });

  return (
    <div className="space-y-6 max-w-4xl">
      <h3 className="text-base font-semibold text-foreground dark:text-foreground flex items-center gap-2">
        <Sparkles className="w-4 h-4 text-purple-500" />
        Źródła AI
      </h3>

      {/* Phase 15: similar historical roles → pre-fill suggestion */}
      <ChampionHistoricalMatchesPanel
        jobId={jobId}
        clientId={clientId ?? null}
        crossClient={historicalCrossClient}
        onToggleCrossClient={setHistoricalCrossClient}
        onSuggestionGenerated={(s) => setActiveSuggestion(s)}
      />

      {/* Pending suggestions */}
      <Section title="Drafty AI do przeglądu" empty="Brak pending draftów.">
        {pending.isLoading && <Loader2 className="w-4 h-4 animate-spin" />}
        {(pending.data?.items ?? []).map((s) => (
          <div
            key={s.id}
            className="flex items-center justify-between gap-3 border border-border dark:border-border rounded-lg p-3"
          >
            <div className="text-sm">
              <div className="font-medium text-foreground dark:text-foreground">
                {sourceLabel(s.source_type)}
              </div>
              <div className="text-xs text-muted-foreground">
                {new Date(s.created_at).toLocaleString("pl-PL")}
                {" · "}
                {s.patches.length} sekcji do akceptacji
              </div>
            </div>
            <button
              type="button"
              onClick={() => setActiveSuggestion(s)}
              className="px-3 py-1 text-sm rounded-lg bg-primary hover:bg-primary/90 text-white"
            >
              Przejrzyj
            </button>
          </div>
        ))}
      </Section>

      {/* Attached meetings */}
      <Section
        title="Powiązane rozmowy"
        empty="Żadne meetingi nie są powiązane z tą ofertą."
      >
        {(attached.data?.items ?? [])
          .filter((n) => n.note_type === "meeting")
          .map((n) => (
            <div
              key={n.id}
              className="flex items-center gap-3 border border-border dark:border-border rounded-lg p-3 text-sm"
            >
              <Link2 className="w-4 h-4 text-muted-foreground" />
              <div className="flex-1">
                <div className="font-medium text-foreground dark:text-foreground truncate">
                  {noteTitle(n.content)}
                </div>
                <div className="text-xs text-muted-foreground">
                  {new Date(n.created_at).toLocaleString("pl-PL")}
                </div>
              </div>
            </div>
          ))}
      </Section>

      {/* Unlinked recent meetings */}
      <Section
        title="Meetingi bez powiązania"
        empty="Wszystkie meetingi zostały już powiązane."
      >
        {unlinkedMeetings.slice(0, 10).map((n) => (
          <div
            key={n.id}
            className="flex items-center gap-3 border border-border dark:border-border rounded-lg p-3 text-sm"
          >
            <div className="flex-1 min-w-0">
              <div className="font-medium text-foreground dark:text-foreground truncate">
                {noteTitle(n.content)}
              </div>
              <div className="text-xs text-muted-foreground">
                {new Date(n.created_at).toLocaleString("pl-PL")}
              </div>
            </div>
            <button
              type="button"
              onClick={() => linkMutation.mutate(n.id)}
              disabled={linkMutation.isPending}
              className="px-3 py-1 text-sm rounded-lg bg-purple-600 hover:bg-purple-700 text-white disabled:opacity-60 inline-flex items-center gap-1.5"
            >
              {linkMutation.isPending ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Link2 className="w-3.5 h-3.5" />
              )}
              Powiąż + AI
            </button>
          </div>
        ))}
      </Section>

      {activeSuggestion && (
        <ChampionProfileSuggestionReview
          jobId={jobId}
          suggestion={activeSuggestion}
          currentProfile={currentProfile}
          onClose={() => setActiveSuggestion(null)}
        />
      )}
    </div>
  );
}

// ── Helpers ────────────────────────────────────────────────────────────────

function Section({
  title,
  empty,
  children,
}: {
  title: string;
  empty: string;
  children: React.ReactNode;
}) {
  const kids = Array.isArray(children) ? children : [children];
  const hasContent = kids.some((c) => c);
  return (
    <div className="space-y-2">
      <div className="text-xs uppercase tracking-wide text-muted-foreground font-semibold">
        {title}
      </div>
      {hasContent ? (
        <div className="space-y-2">{children}</div>
      ) : (
        <div className="text-sm italic text-muted-foreground">{empty}</div>
      )}
    </div>
  );
}

function sourceLabel(source: ChampionProfileSuggestion["source_type"]): string {
  switch (source) {
    case "jd_paste":
      return "Opis od klienta (paste)";
    case "fireflies_meeting":
      return "Meeting Fireflies";
    case "cloudtalk_call":
      return "Rozmowa CloudTalk";
    case "manual_consultant_note":
      return "Notatka konsultanta";
    case "historical_jobs":
      return "Podobne role z przeszłości";
    default:
      return source;
  }
}
