"use client";

import { useQuery } from "@tanstack/react-query";
import { contractsApi, type ContractTimelineItem } from "@/lib/api";
import { Phone, StickyNote } from "lucide-react";
import { formatDate } from "@/lib/utils";

interface Props {
  contractId: number;
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

export function ContractNotesTab({ contractId }: Props) {
  const { data: items = [], isLoading } = useQuery({
    queryKey: ["contract-notes-timeline", contractId],
    queryFn: async () => {
      const res = await contractsApi.notesTimeline(contractId);
      return res.data as ContractTimelineItem[];
    },
  });

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Ładowanie historii…</p>;
  }

  if (items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground italic">
        Brak notatek ani rozmów powiązanych z tym kontraktem. Powiąż istniejące
        rekordy ustawiając <code>contract_id</code>, albo dodaj nowe z poziomu
        kandydata.
      </p>
    );
  }

  return (
    <div className="space-y-3">
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
