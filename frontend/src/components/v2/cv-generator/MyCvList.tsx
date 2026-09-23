"use client";

import { useId, useMemo, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { CvGeneratedShareModal } from "@/components/v2/modals/CvGeneratedShareModal";
import { cvGeneratorApi, type GeneratedCvItem } from "@/lib/api";
import { CV_CLIENT_LINKS_UI_ENABLED } from "@/lib/cv-generator";
import { useDebouncedValue } from "@/lib/use-debounced-value";

import { CvResultLive } from "./CvResult";
import { GeneratedCvRow } from "./GeneratedCvRow";
import { Segmented } from "./GeneratorParts";

const PAGE = 60;

export type MyCvScope = "mine" | "all";
export type MyCvDays = 30 | 90;

/** Wiersze listy: pakiet „Obie” jako JEDEN wiersz z dwiema wersjami języka. */
export function groupPackageRows(items: readonly GeneratedCvItem[]): Array<{ item: GeneratedCvItem; siblings: GeneratedCvItem[] }> {
  const ids = new Set(items.map((item) => item.id));
  return items
    .filter((item) => !item.package_id || item.package_id === item.id || !ids.has(item.package_id))
    .map((item) => ({
      item,
      siblings: items.filter((other) => other.id !== item.id && other.package_id === item.id),
    }));
}

export interface MyCvListViewProps {
  items: readonly GeneratedCvItem[];
  loading: boolean;
  error: boolean;
  /** Lista zawężona do osoby/rekrutacji (okno z procesu) — bez filtrów. */
  scoped?: boolean;
  scope: MyCvScope;
  onScopeChange: (scope: MyCvScope) => void;
  days: MyCvDays;
  onDaysChange: (days: MyCvDays) => void;
  query: string;
  onQueryChange: (value: string) => void;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
  onOpen: (item: GeneratedCvItem) => void;
  onRetry?: (item: GeneratedCvItem) => void;
  onSelectForRecruitment?: (item: { id: number; filename: string }) => void;
  onShare?: (item: GeneratedCvItem) => void;
  selectedGeneratedId?: number | null;
  now?: Date;
}

/** Lista „Moje CV” — filtry, tabela, „Pokaż starsze”. Bez sieci. */
export function MyCvListView(props: MyCvListViewProps) {
  const searchId = useId();
  const periodId = useId();
  const rows = useMemo(() => groupPackageRows(props.items), [props.items]);
  const countLabel = `${rows.length}${props.hasMore ? "+" : ""} CV`;

  return (
    <section aria-label="Moje CV" className="rounded-xl border border-border bg-card">
      {!props.scoped ? (
        <div className="flex flex-wrap items-end gap-4 border-b border-border p-4">
          <Segmented<MyCvScope>
            label="Czyje CV"
            value={props.scope}
            onChange={props.onScopeChange}
            options={[{ value: "mine", label: "Moje" }, { value: "all", label: "Wszyscy" }]}
          />
          <div className="space-y-1">
            <label htmlFor={periodId} className="block text-xs font-medium text-muted-foreground">Okres</label>
            <select
              id={periodId}
              value={props.days}
              onChange={(event) => props.onDaysChange(Number(event.target.value) === 90 ? 90 : 30)}
              className="h-9 rounded-lg border border-border bg-card px-3 text-sm text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <option value={30}>Ostatnie 30 dni</option>
              <option value={90}>Ostatnie 90 dni</option>
            </select>
          </div>
          <div className="min-w-[14rem] flex-1 space-y-1">
            <label htmlFor={searchId} className="block text-xs font-medium text-muted-foreground">Szukaj osoby</label>
            <div className="relative">
              <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id={searchId}
                value={props.query}
                onChange={(event) => props.onQueryChange(event.target.value)}
                placeholder="Imię albo nazwisko"
                className="h-9 pl-9"
              />
            </div>
          </div>
          <p className="ml-auto text-sm text-muted-foreground" aria-live="polite">{countLabel}</p>
        </div>
      ) : null}

      {props.loading ? (
        <p className="p-4 text-sm text-muted-foreground" role="status">Wczytuję listę CV…</p>
      ) : props.error ? (
        <p className="p-4 text-sm text-destructive" role="alert">
          Nie udało się pobrać listy CV. Spróbuj ponownie za chwilę.
        </p>
      ) : rows.length === 0 ? (
        <p className="p-4 text-sm text-muted-foreground">
          {props.query.trim()
            ? "Nikt o tym nazwisku nie ma CV w wybranym okresie."
            : props.scoped
              ? "Brak wygenerowanych CV tej osoby w tej rekrutacji."
              : `Brak CV z ostatnich ${props.days} dni.`}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="border-b border-border bg-muted/40 text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">Osoba</th>
                <th scope="col" className="px-3 py-2 font-medium">Proces / klient</th>
                <th scope="col" className="px-3 py-2 font-medium">Język</th>
                <th scope="col" className="px-3 py-2 font-medium">Obróbka</th>
                <th scope="col" className="px-3 py-2 font-medium">Do sprawdzenia</th>
                <th scope="col" className="px-3 py-2 font-medium">Wygenerowano</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Akcje</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map(({ item, siblings }) => (
                <GeneratedCvRow
                  key={item.id}
                  item={item}
                  siblings={siblings}
                  now={props.now}
                  onOpen={props.onOpen}
                  onRetry={props.onRetry}
                  onSelectForRecruitment={props.onSelectForRecruitment}
                  onShare={props.onShare}
                  selected={props.selectedGeneratedId === item.id}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3 border-t border-border px-4 py-3">
        {props.hasMore ? (
          <Button type="button" variant="outline" size="sm" disabled={props.loadingMore} onClick={props.onLoadMore}>
            {props.loadingMore ? "Wczytuję…" : "Pokaż starsze"}
          </Button>
        ) : null}
        <p className="text-xs text-muted-foreground">
          „Otwórz” pokazuje ten sam widok co po generacji: podgląd, edycję, pobranie i rzeczy do sprawdzenia.
        </p>
      </div>
    </section>
  );
}

export interface MyCvListProps {
  /** Zawężenie do osoby (i rekrutacji) — okno z procesu. */
  candidateId?: number;
  jobId?: number | null;
  canWrite: boolean;
  onRetry?: (item: GeneratedCvItem) => void;
  onSelectForRecruitment?: (item: { id: number; filename: string }) => void;
  selectedGeneratedId?: number | null;
}

/** Lista „Moje CV” z serwera: Moje/Wszyscy, okres 30/90 dni, szukanie osoby. */
export function MyCvList(props: MyCvListProps) {
  const scoped = props.candidateId != null;
  const [scope, setScope] = useState<MyCvScope>("mine");
  const [days, setDays] = useState<MyCvDays>(30);
  const [query, setQuery] = useState("");
  const [openItem, setOpenItem] = useState<GeneratedCvItem | null>(null);
  const [shareItem, setShareItem] = useState<GeneratedCvItem | null>(null);
  const canShare = props.canWrite && CV_CLIENT_LINKS_UI_ENABLED;
  const debouncedQuery = useDebouncedValue(query.trim(), 300);

  const listQuery = useInfiniteQuery({
    queryKey: ["cv-my-list", scoped ? "scoped" : scope, scoped ? null : days, scoped ? "" : debouncedQuery, props.candidateId ?? null, props.jobId ?? null],
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last: GeneratedCvItem[]) => (last.length === PAGE ? last[last.length - 1].id : undefined),
    queryFn: async ({ pageParam }) =>
      (await cvGeneratorApi.listGenerated(
        scoped
          ? { candidate_id: props.candidateId, job_id: props.jobId ?? undefined, before_id: pageParam, limit: PAGE }
          : { mine: scope === "mine", days, q: debouncedQuery || undefined, before_id: pageParam, limit: PAGE },
      )).data,
    staleTime: 15_000,
    // Generacja leci w tle — dopóki któreś CV się generuje, odpytuj listę.
    refetchInterval: (q) =>
      q.state.data?.pages.some((page) => page.some((row) => row.status === "processing")) ? 4000 : false,
  });
  const items = useMemo(() => listQuery.data?.pages.flat() ?? [], [listQuery.data]);

  return (
    <>
      <MyCvListView
        items={items}
        loading={listQuery.isPending}
        error={listQuery.isError}
        scoped={scoped}
        scope={scope}
        onScopeChange={setScope}
        days={days}
        onDaysChange={setDays}
        query={query}
        onQueryChange={setQuery}
        hasMore={!!listQuery.hasNextPage}
        loadingMore={listQuery.isFetchingNextPage}
        onLoadMore={() => void listQuery.fetchNextPage()}
        onOpen={setOpenItem}
        onRetry={props.onRetry}
        onSelectForRecruitment={props.onSelectForRecruitment}
        onShare={canShare ? setShareItem : undefined}
        selectedGeneratedId={props.selectedGeneratedId}
      />
      {canShare ? (
        <CvGeneratedShareModal
          generatedId={shareItem?.id ?? null}
          candidateName={shareItem?.candidate_name}
          onClose={() => setShareItem(null)}
        />
      ) : null}
      <Dialog open={!!openItem} onOpenChange={(open) => !open && setOpenItem(null)}>
        <DialogContent size="2xl" aria-describedby={undefined}>
          <DialogTitle className="sr-only">Wygenerowane CV</DialogTitle>
          <div className="min-h-0 flex-1 overflow-y-auto p-5">
            {openItem ? (
              <CvResultLive
                mainId={openItem.package_id && openItem.package_id !== openItem.id ? openItem.package_id : openItem.id}
                candidateId={openItem.candidate_id}
                jobId={openItem.job_id}
                canWrite={props.canWrite}
                onRegenerate={props.onRetry ? () => { const item = openItem; setOpenItem(null); props.onRetry?.(item); } : undefined}
                onDeleted={() => setOpenItem(null)}
              />
            ) : null}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
