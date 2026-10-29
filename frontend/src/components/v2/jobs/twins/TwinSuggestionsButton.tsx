"use client";

/**
 * „⇄ N możliwych bliźniaków” na liście rekrutacji — tylko Head of
 * Recruitment i admin (0614, decyzja Artura 28.10.2026). Delivery Lead zna
 * swoje requesty, więc lista pokazuje pary otwartych rekrutacji z RÓŻNYMI
 * DL-ami (często u różnych klientów), jeszcze nie połączone i nie odrzucone.
 * „⇄ Połącz” otwiera to samo okno porównania co w rekrutacji; „To nie
 * bliźniak” chowa parę na stałe.
 */

import { useState } from "react";
import Link from "next/link";
import { ArrowLeftRight } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiErrorMessage } from "@/lib/api-error";
import {
  budgetLabel,
  twinRef,
  type TwinJobBrief,
  type TwinSuggestion,
  useDismissTwinSuggestion,
  useTwinSuggestions,
  workModeLabel,
} from "@/lib/job-twins-api";

import { TwinLinkDialog } from "./TwinLinkDialog";

function pluralTwins(n: number): string {
  if (n === 1) return "możliwy bliźniak";
  const last = n % 10;
  const lastTwo = n % 100;
  return last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14) ? "możliwe bliźniaki" : "możliwych bliźniaków";
}

function JobLine({ job }: { job: TwinJobBrief }) {
  return (
    <p className="min-w-0 text-sm">
      <span className="mr-1.5 font-mono text-xs">{twinRef(job)}</span>
      <Link href={`/jobs/${job.id}`} className="font-medium hover:underline">
        {job.title}
      </Link>
      <span className="block truncate text-xs text-muted-foreground">
        {job.client_name ?? "—"} · DL {job.delivery_lead_name ?? "brak"} · {workModeLabel(job)} · {budgetLabel(job)}
      </span>
    </p>
  );
}

export interface TwinSuggestionListProps {
  items: readonly TwinSuggestion[];
  onLink: (item: TwinSuggestion) => void;
  onDismiss: (item: TwinSuggestion) => void;
  busyKey?: string | null;
}

export function TwinSuggestionList({ items, onLink, onDismiss, busyKey }: TwinSuggestionListProps) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">Nie ma par do przejrzenia.</p>;
  }
  return (
    <ul className="divide-y divide-border rounded-lg border border-border" data-testid="twin-suggestions">
      {items.map((item) => {
        const key = `${item.job.id}-${item.other.id}`;
        return (
          <li key={key} className="grid gap-2 px-3 py-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
            <div className="grid min-w-0 gap-1">
              <JobLine job={item.job} />
              <JobLine job={item.other} />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs tabular-nums text-muted-foreground">≈ {item.similarity}%</span>
              <Button size="sm" onClick={() => onLink(item)}>
                <ArrowLeftRight className="h-3.5 w-3.5" aria-hidden="true" />
                Połącz
              </Button>
              <Button size="sm" variant="outline" disabled={busyKey === key} onClick={() => onDismiss(item)}>
                To nie bliźniak
              </Button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function TwinSuggestionsButton() {
  const { showError } = useToast();
  const query = useTwinSuggestions(true);
  const dismiss = useDismissTwinSuggestion();
  const [open, setOpen] = useState(false);
  const [linking, setLinking] = useState<TwinSuggestion | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const items = query.data?.items ?? [];
  if (!query.isSuccess || items.length === 0) return null;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        data-testid="twin-suggestions-button"
        className="inline-flex items-center gap-1 rounded-md border border-dashed border-primary/40 px-2 py-1 text-xs font-medium text-primary hover:bg-primary/10"
      >
        <ArrowLeftRight className="h-3 w-3" aria-hidden="true" />
        {items.length} {pluralTwins(items.length)}
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent size="lg" aria-describedby="twin-suggestions-desc">
          <DialogHeader>
            <DialogTitle>Możliwe bliźniaki</DialogTitle>
            <DialogDescription id="twin-suggestions-desc">
              Otwarte rekrutacje bardzo podobne do siebie (≈ {query.data.min_similarity}% i więcej), prowadzone przez
              różnych Delivery Leadów. Połączone weryfikujecie w jednej rozmowie.
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            <TwinSuggestionList
              items={items}
              busyKey={busyKey}
              onLink={(item) => {
                setOpen(false);
                setLinking(item);
              }}
              onDismiss={(item) => {
                const key = `${item.job.id}-${item.other.id}`;
                setBusyKey(key);
                dismiss
                  .mutateAsync({ jobId: item.job.id, otherId: item.other.id })
                  .catch((error: unknown) => showError(apiErrorMessage(error, "Nie udało się odrzucić pary.")))
                  .finally(() => setBusyKey(null));
              }}
            />
          </DialogBody>
        </DialogContent>
      </Dialog>
      {linking ? (
        <TwinLinkDialog
          jobId={linking.job.id}
          otherJobId={linking.other.id}
          open
          onOpenChange={(next) => {
            if (!next) setLinking(null);
          }}
        />
      ) : null}
    </>
  );
}
