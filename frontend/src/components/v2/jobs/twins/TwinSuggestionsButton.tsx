"use client";

/**
 * „⇄ Bliźniaki” na liście rekrutacji — tylko Head of Recruitment i admin
 * (0614, decyzja Artura 28.10.2026). Delivery Lead zna swoje requesty, więc
 * podpowiedzi to pary otwartych rekrutacji z RÓŻNYMI DL-ami (często u różnych
 * klientów), jeszcze nie połączone i nie odrzucone. „⇄ Połącz” otwiera to
 * samo okno porównania co w rekrutacji; „To nie bliźniak” chowa parę na stałe.
 *
 * Od 10.11.2026 przycisk stoi zawsze, także bez podpowiedzi, a okno zaczyna
 * od „Połącz wybrane rekrutacje” (Olaf nie wiedział, jak samemu wybrać
 * requesty i je połączyć): pierwsza z wyszukiwarki, druga w oknie łączenia.
 */

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeftRight, Search } from "lucide-react";

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
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
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
import { useDebouncedValue } from "@/lib/use-debounced-value";

import { RuleChips } from "./OpenSimilarTile";
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
              <RuleChips warnings={item.warnings} />
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

interface OpenJobRow {
  id: number;
  title: string;
  reference_number: string | null;
  client_reference: string | null;
  client_name: string | null;
}

/** Pierwsza rekrutacja pary — dowolna otwarta; drugą wybiera się w oknie łączenia. */
export function ManualTwinPicker({ onPick }: { onPick: (jobId: number, label: string) => void }) {
  const [q, setQ] = useState("");
  const term = useDebouncedValue(q.trim(), 250);
  const search = useQuery({
    queryKey: ["twin-manual-first", term],
    enabled: term.length >= 2,
    queryFn: async ({ signal }) =>
      (
        await api.get<{ items: OpenJobRow[] }>("/api/jobs", {
          params: { q: term, open_only: true, page_size: 8 },
          signal,
        })
      ).data.items,
  });
  const rows = search.data ?? [];
  return (
    <section className="space-y-2" aria-label="Połącz wybrane rekrutacje" data-testid="twin-manual-picker">
      <label
        htmlFor="twin-manual-first"
        className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
      >
        Połącz wybrane rekrutacje
      </label>
      <p className="text-xs text-muted-foreground">
        Wybierz pierwszą rekrutację, drugą wskażesz w następnym kroku. Dowolne otwarte, także spoza podpowiedzi.
      </p>
      <div className="relative">
        <Search
          className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground"
          aria-hidden="true"
        />
        <Input
          id="twin-manual-first"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Pierwsza rekrutacja: numer, tytuł albo klient"
          className="pl-8"
        />
      </div>
      {search.isError ? (
        <p className="text-sm text-destructive">
          {apiErrorMessage(search.error, "Nie udało się wyszukać rekrutacji.")}
        </p>
      ) : rows.length > 0 ? (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {rows.map((row) => {
            const ref = row.client_reference ?? row.reference_number ?? `#${row.id}`;
            return (
              <li key={row.id} className="flex items-center gap-3 px-3 py-2">
                <p className="min-w-0 flex-1 truncate text-sm">
                  <span className="mr-1.5 font-mono text-xs">{ref}</span>
                  {row.title} <span className="text-muted-foreground">· {row.client_name ?? "—"}</span>
                </p>
                <Button size="sm" variant="outline" onClick={() => onPick(row.id, `${ref} ${row.title}`)}>
                  Wybierz
                </Button>
              </li>
            );
          })}
        </ul>
      ) : term.length >= 2 && search.isSuccess ? (
        <p className="text-sm text-muted-foreground">Nic otwartego nie pasuje do „{term}”.</p>
      ) : null}
    </section>
  );
}

export function TwinSuggestionsButton() {
  const { showError } = useToast();
  const query = useTwinSuggestions(true);
  const dismiss = useDismissTwinSuggestion();
  const [open, setOpen] = useState(false);
  const [linking, setLinking] = useState<{
    jobId: number;
    otherId: number | null;
    anchorLabel?: string;
  } | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const items = query.data?.items ?? [];

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        data-testid="twin-suggestions-button"
        data-tour="jobs.list.twins"
        title="Połącz wybrane rekrutacje jako bliźniaki albo przejrzyj podpowiedzi"
        className="inline-flex items-center gap-1 rounded-md border border-dashed border-primary/40 px-2 py-1 text-xs font-medium text-primary hover:bg-primary/10"
      >
        <ArrowLeftRight className="h-3 w-3" aria-hidden="true" />
        Bliźniaki
        {items.length > 0 ? (
          <span className="font-normal">
            · {items.length} {pluralTwins(items.length)}
          </span>
        ) : null}
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent size="lg" aria-describedby="twin-suggestions-desc">
          <DialogHeader>
            <DialogTitle>Bliźniaki</DialogTitle>
            <DialogDescription id="twin-suggestions-desc">
              Bliźniaki to rekrutacje o tym samym profilu kandydata. Połączone weryfikujecie w jednej rozmowie.
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-5">
            <ManualTwinPicker
              onPick={(jobId, anchorLabel) => {
                setOpen(false);
                setLinking({ jobId, otherId: null, anchorLabel });
              }}
            />
            <section className="space-y-2" aria-label="Możliwe bliźniaki">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Możliwe bliźniaki</h3>
              {query.isError ? (
                <p className="text-sm text-destructive">Nie udało się pobrać podpowiedzi.</p>
              ) : !query.isSuccess ? (
                <p className="text-sm text-muted-foreground">Szukam podpowiedzi…</p>
              ) : (
                <>
                  <p className="text-xs text-muted-foreground">
                    Otwarte rekrutacje różnych DL-i podobne do siebie (≈ {query.data.min_similarity}% i więcej), które
                    spełniają zasady wymagane z Ustawień → Rekrutacja → Zasady bliźniaków.
                  </p>
                  <TwinSuggestionList
                    items={items}
                    busyKey={busyKey}
                    onLink={(item) => {
                      setOpen(false);
                      setLinking({
                        jobId: item.job.id,
                        otherId: item.other.id,
                      });
                    }}
                    onDismiss={(item) => {
                      const key = `${item.job.id}-${item.other.id}`;
                      setBusyKey(key);
                      dismiss
                        .mutateAsync({
                          jobId: item.job.id,
                          otherId: item.other.id,
                        })
                        .catch((error: unknown) => showError(apiErrorMessage(error, "Nie udało się odrzucić pary.")))
                        .finally(() => setBusyKey(null));
                    }}
                  />
                </>
              )}
            </section>
          </DialogBody>
        </DialogContent>
      </Dialog>
      {linking ? (
        <TwinLinkDialog
          jobId={linking.jobId}
          otherJobId={linking.otherId}
          anchorLabel={linking.anchorLabel}
          open
          onOpenChange={(next) => {
            if (!next) setLinking(null);
          }}
        />
      ) : null}
    </>
  );
}
