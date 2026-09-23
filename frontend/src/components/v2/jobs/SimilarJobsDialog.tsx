"use client";

/**
 * „Podobne rekrutacje" (0341) — wybór rekrutacji podobnych do tej i przepięcie
 * osób wysłanych tam do klienta do „Do przejrzenia".
 *
 * Sugestie liczy serwer (wspólne must-have, tytuł, kategoria kompetencji);
 * domyślnie zaznaczone są te, w których ktoś był już u klienta. Rekruter albo
 * DL może też dopisać własną rekrutację z wyszukiwarki. Połączenie jest
 * trwałe: kolejne osoby wysłane w połączonej rekrutacji przepinają się same.
 */

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link2, Search, Unlink } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import {
  selectedSentCount,
  type SimilarJobItem,
  useLinkSimilarJobs,
  useSimilarJobs,
  useUnlinkSimilarJob,
} from "@/lib/similar-jobs-api";
import { cn } from "@/lib/utils";

interface SearchRow {
  id: number;
  title: string;
  client_name?: string | null;
  reference_number?: string | null;
  status?: string;
}

export function SimilarJobsDialog({
  jobId,
  open,
  onOpenChange,
}: {
  jobId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { showSuccess, showError } = useToast();
  const similar = useSimilarJobs(jobId, open);
  const link = useLinkSimilarJobs(jobId);
  const unlink = useUnlinkSimilarJob(jobId);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [manual, setManual] = useState<SimilarJobItem[]>([]);
  const [query, setQuery] = useState("");
  const [seeded, setSeeded] = useState(false);

  useEffect(() => {
    if (!open) {
      setSeeded(false);
      setManual([]);
      setQuery("");
      return;
    }
    // Nic nie jest zaznaczone z góry (test na produkcji 23.09.2026): połączenie
    // przepina ludzi do tej rekrutacji, więc wybiera je wyłącznie człowiek.
    if (!seeded && similar.data) {
      setSelected(new Set());
      setSeeded(true);
    }
  }, [open, seeded, similar.data]);

  const search = useQuery({
    queryKey: ["similar-jobs-search", jobId, query.trim()],
    queryFn: () =>
      api
        .get<{ items: SearchRow[] }>("/api/jobs", {
          params: { q: query.trim(), page_size: 8 },
        })
        .then((r) => r.data.items),
    enabled: open && query.trim().length >= 2,
    staleTime: 30_000,
  });

  const linkedIds = useMemo(
    () => new Set((similar.data?.linked ?? []).map((j) => j.id)),
    [similar.data],
  );
  const options = useMemo(() => {
    const base = similar.data?.suggestions ?? [];
    const known = new Set(base.map((s) => s.id));
    return [...base, ...manual.filter((m) => !known.has(m.id))];
  }, [similar.data, manual]);
  const toReassign = selectedSentCount(options, selected);

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const addManual = (row: SearchRow) => {
    if (row.id === jobId || linkedIds.has(row.id)) return;
    setManual((prev) =>
      prev.some((m) => m.id === row.id)
        ? prev
        : [
            ...prev,
            {
              id: row.id,
              title: row.title,
              client_name: row.client_name ?? null,
              reference_number: row.reference_number ?? null,
              status: row.status ?? "",
              closed_at: null,
              similarity: null,
              sent_count: 0,
              linked: false,
            },
          ],
    );
    setSelected((prev) => new Set(prev).add(row.id));
    setQuery("");
  };

  const submit = async () => {
    const ids = [...selected];
    if (ids.length === 0) return;
    try {
      const result = await link.mutateAsync(ids);
      showSuccess(
        result.reassigned_now > 0
          ? `Połączono. Przepięto ${result.reassigned_now} ${plural(result.reassigned_now)} do „Do przejrzenia”.`
          : "Połączono. Nikt nie czekał na przepięcie — kolejne osoby wysłane do klienta przepną się same.",
      );
      onOpenChange(false);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się połączyć rekrutacji."));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg" aria-describedby="similar-jobs-desc">
        <DialogHeader>
          <DialogTitle>Podobne rekrutacje</DialogTitle>
          <DialogDescription id="similar-jobs-desc">
            Osoby wysłane do klienta w zaznaczonych rekrutacjach trafią do
            „Do przejrzenia” jako przepięcia. Kolejne przepną się same.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-5">
          {similar.isError ? (
            <p className="text-sm text-destructive">
              Nie udało się wczytać podobnych rekrutacji.{" "}
              <button
                type="button"
                className="font-medium underline"
                onClick={() => similar.refetch()}
              >
                Ponów
              </button>
            </p>
          ) : null}

          {similar.data && similar.data.linked.length > 0 ? (
            <section aria-label="Połączone">
              <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Połączone · przepięto {similar.data.reassigned_count}
              </h3>
              <ul className="space-y-1">
                {similar.data.linked.map((item) => (
                  <li
                    key={item.id}
                    className="flex items-center gap-3 rounded-lg border border-border px-3 py-2"
                  >
                    <Link2 className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
                    <JobLabel item={item} />
                    <span className="ml-auto whitespace-nowrap text-xs text-muted-foreground">
                      {item.sent_count} u klienta
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => unlink.mutate(item.id)}
                      disabled={unlink.isPending}
                      aria-label={`Rozłącz: ${item.title}`}
                    >
                      <Unlink className="h-3.5 w-3.5" />
                    </Button>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <section aria-label="Sugerowane">
            <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Sugerowane przez system
            </h3>
            {similar.isLoading ? (
              <p className="text-sm text-muted-foreground">Szukam podobnych rekrutacji…</p>
            ) : options.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                System nie znalazł podobnych rekrutacji. Dodaj je samodzielnie poniżej.
              </p>
            ) : (
              <ul className="space-y-1">
                {options.map((item) => {
                  const checked = selected.has(item.id);
                  return (
                    <li key={item.id}>
                      <label
                        className={cn(
                          "flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2",
                          checked ? "bg-primary/5" : "hover:bg-muted",
                        )}
                      >
                        <Checkbox
                          checked={checked}
                          onCheckedChange={() => toggle(item.id)}
                          aria-label={item.title}
                        />
                        <JobLabel item={item} />
                        {item.similarity != null ? (
                          <span className="ml-auto w-10 text-right text-sm font-semibold tabular-nums text-primary">
                            {item.similarity}%
                          </span>
                        ) : (
                          <span className="ml-auto text-xs text-muted-foreground">dodana</span>
                        )}
                        <span className="w-24 whitespace-nowrap text-right text-xs text-muted-foreground">
                          <b className="font-semibold text-foreground">{item.sent_count}</b>{" "}
                          u klienta
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section aria-label="Dodaj samodzielnie">
            <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Dodaj samodzielnie
            </h3>
            <div className="relative">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden="true"
              />
              <Input
                id="similar-jobs-search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Szukaj rekrutacji po tytule, kliencie, numerze…"
                className="pl-9"
              />
            </div>
            {query.trim().length >= 2 ? (
              <ul className="mt-1 max-h-48 overflow-y-auto rounded-lg border border-border">
                {(search.data ?? [])
                  .filter((r) => r.id !== jobId && !linkedIds.has(r.id))
                  .map((row) => (
                    <li key={row.id}>
                      <button
                        type="button"
                        onClick={() => addManual(row)}
                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted"
                      >
                        <span className="font-medium">{row.title}</span>
                        <span className="text-xs text-muted-foreground">
                          {[row.client_name, row.reference_number].filter(Boolean).join(" · ")}
                        </span>
                      </button>
                    </li>
                  ))}
                {search.isSuccess &&
                (search.data ?? []).filter((r) => r.id !== jobId && !linkedIds.has(r.id))
                  .length === 0 ? (
                  <li className="px-3 py-2 text-sm text-muted-foreground">Brak wyników.</li>
                ) : null}
              </ul>
            ) : null}
          </section>
        </DialogBody>
        <DialogFooter className="items-center">
          <span className="mr-auto text-sm text-muted-foreground">
            {selected.size === 0
              ? "Zaznacz rekrutacje do połączenia."
              : `Do przepięcia: do ${toReassign} ${plural(toReassign)} (bez osób już w tej rekrutacji).`}
          </span>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={selected.size === 0 || link.isPending}>
            {link.isPending ? "Łączę…" : "Połącz i przepnij"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function JobLabel({ item }: { item: SimilarJobItem }) {
  return (
    <span className="min-w-0">
      <span className="block truncate text-sm font-medium">{item.title}</span>
      <span className="block truncate text-xs text-muted-foreground">
        {[item.client_name, item.reference_number, item.status === "closed" ? "zamknięta" : null]
          .filter(Boolean)
          .join(" · ")}
      </span>
    </span>
  );
}

export function plural(n: number): string {
  if (n === 1) return "osobę";
  const lastTwo = n % 100;
  const last = n % 10;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return "osoby";
  return "osób";
}
