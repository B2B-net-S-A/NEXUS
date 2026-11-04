"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { contractsApi, type ContractTimelineItem } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { useToast } from "@/components/Toast";
import { Phone, StickyNote } from "lucide-react";
// DD.MM.RRRR jak reszta kontraktu (audyt 24.09, N8).
import { formatIsoDatePl as formatDate } from "@/lib/date-pl";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { resolveViewState } from "@/lib/view-state";

interface Props {
  contractId: number;
  /** Runda 10 (F03): admin i Delivery Lead dopisują notatkę wprost przy
   *  kontrakcie (backend: `POST /api/contracts/{id}/notes`). */
  canAddNote?: boolean;
}

type NewNoteType = "general" | "call" | "meeting" | "email";

const NEW_NOTE_TYPES: { value: NewNoteType; label: string }[] = [
  { value: "general", label: "Notatka" },
  { value: "call", label: "Rozmowa" },
  { value: "meeting", label: "Spotkanie" },
  { value: "email", label: "Email" },
];

function AddContractNoteForm({ contractId }: { contractId: number }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [content, setContent] = useState("");
  const [noteType, setNoteType] = useState<NewNoteType>("general");
  const mutation = useMutation({
    mutationFn: () =>
      contractsApi.createNote(contractId, {
        content: content.trim(),
        note_type: noteType,
      }),
    onSuccess: () => {
      setContent("");
      setNoteType("general");
      void queryClient.invalidateQueries({
        queryKey: ["contract-notes-timeline", contractId],
      });
      showToast("Notatka zapisana przy kontrakcie", "success");
    },
    onError: (err) => {
      showToast(apiErrorMessage(err, "Nie udało się zapisać notatki."), "error");
    },
  });
  const canSubmit = content.trim().length > 0 && !mutation.isPending;
  return (
    <form
      className="space-y-2 rounded-lg border border-border p-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (canSubmit) mutation.mutate();
      }}
    >
      <label
        htmlFor={`contract-note-${contractId}`}
        className="block text-xs font-medium text-muted-foreground"
      >
        Nowa notatka przy kontrakcie
      </label>
      <textarea
        id={`contract-note-${contractId}`}
        value={content}
        onChange={(e) => setContent(e.target.value)}
        rows={3}
        maxLength={20000}
        className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
        placeholder="Np. ustalenia z rozmowy z konsultantem albo klientem"
      />
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="Rodzaj notatki"
          value={noteType}
          onChange={(e) => setNoteType(e.target.value as NewNoteType)}
          className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
        >
          {NEW_NOTE_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
        <button
          type="submit"
          disabled={!canSubmit}
          className="ml-auto rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          {mutation.isPending ? "Zapisywanie…" : "Dodaj notatkę"}
        </button>
      </div>
      <p className="text-xs text-muted-foreground">
        Notatka będzie też widoczna w profilu kandydata.
      </p>
    </form>
  );
}

const DIRECTION_LABELS: Record<string, string> = {
  inbound: "Połączenie przychodzące",
  outbound: "Połączenie wychodzące",
};

const NOTE_TYPE_LABELS: Record<string, string> = {
  call: "Rozmowa",
  meeting: "Spotkanie",
  email: "Email",
  general: "Notatka",
  interview: "Interview",
};

function formatDuration(seconds: number | null): string {
  if (!seconds) return "";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s`;
}

export function ContractNotesTab({ contractId, canAddNote = false }: Props) {
  const notesQuery = useQuery({
    queryKey: ["contract-notes-timeline", contractId],
    queryFn: async () => {
      const res = await contractsApi.notesTimeline(contractId);
      return res.data as ContractTimelineItem[];
    },
  });
  const items = notesQuery.data ?? [];
  const viewState = resolveViewState({
    isLoading: notesQuery.isLoading,
    error: notesQuery.error,
    isSuccess: notesQuery.isSuccess,
    isEmpty: items.length === 0,
  });

  if (viewState === "loading") {
    return <p className="text-sm text-muted-foreground">Ładowanie historii…</p>;
  }

  // Awaria NIE może udawać „brak notatek" — to zdanie zachęca do dopisywania
  // rekordów, które mogą już istnieć (audyt FE-03).
  if (
    viewState === "forbidden" ||
    viewState === "not_found" ||
    viewState === "error"
  ) {
    return (
      <QueryStateNotice
        state={viewState}
        onRetry={() => void notesQuery.refetch()}
      />
    );
  }

  const form = canAddNote ? <AddContractNoteForm contractId={contractId} /> : null;

  if (items.length === 0) {
    // Runda 10 (F03): wcześniej zdanie kazało „ustawić contract_id" albo dodać
    // notatkę z kandydata — formularz kandydata nie ma wyboru kontraktu.
    return (
      <div className="space-y-3">
        {form}
        <p className="text-sm text-muted-foreground italic">
          Brak notatek ani rozmów przy tym kontrakcie.
          {canAddNote
            ? " Dodaj pierwszą notatkę w formularzu powyżej."
            : " Notatki przy kontrakcie dodaje administrator albo Delivery Lead."}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {form}
      {items.map((item) => {
        const Icon = item.kind === "call" ? Phone : StickyNote;
        const label =
          item.kind === "call"
            ? DIRECTION_LABELS[item.sub_type || ""] || "Rozmowa"
            : NOTE_TYPE_LABELS[item.sub_type || ""] || "Notatka";
        return (
          <div
            key={`${item.kind}-${item.id}`}
            className="rounded-lg border border-border dark:border-border p-3 bg-card dark:bg-card"
          >
            <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1.5">
              <Icon className="w-3.5 h-3.5" />
              <span className="font-medium text-foreground dark:text-muted-foreground">
                {label}
              </span>
              {item.status && <span>· {item.status}</span>}
              {item.duration_seconds != null && (
                <span>· {formatDuration(item.duration_seconds)}</span>
              )}
              <span className="ml-auto">{formatDate(item.at)}</span>
            </div>
            {item.summary && (
              <p className="text-sm font-medium text-foreground dark:text-foreground mb-1">
                {item.summary}
              </p>
            )}
            {item.content && (
              <p className="text-sm text-foreground dark:text-muted-foreground whitespace-pre-wrap">
                {item.content}
              </p>
            )}
            {item.author_name && (
              <div className="text-xs text-muted-foreground mt-2">
                {item.author_name}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
