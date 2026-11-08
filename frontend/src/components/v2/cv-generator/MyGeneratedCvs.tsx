"use client";

import { useState } from "react";
import Link from "next/link";
import { useInfiniteQuery } from "@tanstack/react-query";
import { FileText, Search } from "lucide-react";

import { cvGeneratorApi, type GeneratedCvItem } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadBlob } from "@/lib/cv-generator";
import { fetchStageCvFile } from "@/lib/stage-cv-file";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { resolveViewState } from "@/lib/view-state";
import { useToast } from "@/components/Toast";
import { EmptyState } from "@/components/ds/EmptyState";
import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { downloadGeneratedCv } from "./cv-generated-files";
import { GeneratedCvPreviewModal } from "./GeneratedCvPreviewModal";

export const MY_CVS_PAGE_SIZE = 50;

const DATE_TIME = new Intl.DateTimeFormat("pl-PL", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Warsaw",
});

/** „07.11.2026, 14:05” w czasie firmy. */
export function formatCvDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "—" : DATE_TIME.format(date);
}

/** Stan pliku słowami — CV etapu (po QC) ma pierwszeństwo przed generatorem. */
export function myCvState(item: GeneratedCvItem): string {
  if (item.status === "processing") return "W trakcie generowania";
  if (item.status === "failed") return "Nie powstało";
  if (item.discarded) return "Odrzucone w rekrutacji";
  if (item.stage_cv_status === "finalized") return "Zatwierdzone w rekrutacji";
  if (item.stage_cv_status === "draft") return "Szkic w rekrutacji";
  return "Z generatora";
}

/** Plik da się otworzyć: CV etapu albo gotowy dokument generatora. */
function canOpen(item: GeneratedCvItem): boolean {
  if (item.status !== "ready") return false;
  return item.stage_cv_stage_id != null || item.can_download;
}

/**
 * „Moje wygenerowane CV” (07.11.2026) — CV z generatora wygenerowane przez
 * zalogowaną osobę: data, kandydat, rekrutacja, podgląd i pobranie. Pytanie do
 * Jarvisa z 20.10 („gdzie mogę znaleźć wygenerowane przeze mnie CV”, dwa razy
 * jednej osoby) — od 13.10.2026 takiej listy nie było (`MyCvList` zniknął
 * z generatorem bez procesu, `generator-cv-tylko-w-rekrutacji.md`).
 *
 * Dane: `GET /api/cv-generator/generated?mine=true` (filtr „Moje CV” został
 * w API). Plik to ten sam, który daje „Pobierz” w plikach kandydata: CV
 * podpięte w rekrutacji idzie z CV etapu (z poprawkami i po QC), reszta
 * z generatora.
 */
export function MyGeneratedCvs() {
  const { showError } = useToast();
  const [search, setSearch] = useState("");
  const q = useDebouncedValue(search.trim(), 300);
  const [previewItem, setPreviewItem] = useState<GeneratedCvItem | null>(null);

  const query = useInfiniteQuery({
    queryKey: ["my-generated-cvs", q],
    queryFn: ({ pageParam }) =>
      cvGeneratorApi
        .listGenerated({
          mine: true,
          limit: MY_CVS_PAGE_SIZE,
          ...(q ? { q } : {}),
          ...(pageParam ? { before_id: pageParam } : {}),
        })
        .then((r) => (Array.isArray(r.data) ? r.data : [])),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) =>
      last.length >= MY_CVS_PAGE_SIZE ? last[last.length - 1]?.id : undefined,
    retry: false,
    staleTime: 30_000,
    // Wiersz „W trakcie generowania” sam przechodzi w gotowy.
    refetchInterval: (state) =>
      state.state.data?.pages.some((page) => page.some((item) => item.status === "processing"))
        ? 5_000
        : false,
  });
  const items = query.data?.pages.flat() ?? [];
  const viewState = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isEmpty: items.length === 0,
    isSuccess: query.isSuccess,
  });

  async function download(item: GeneratedCvItem) {
    const stageId = item.stage_cv_stage_id;
    if (stageId == null) {
      const problem = await downloadGeneratedCv(item, "docx", "mine");
      if (problem) showError(problem);
      return;
    }
    try {
      const file = await fetchStageCvFile(stageId, { download: "mine" });
      downloadBlob(file.blob, file.filename || item.filename);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się pobrać CV."));
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Moje wygenerowane CV"
        description="Twoje CV z generatora, od najnowszego. Gotowe CV są też w plikach kandydata i w rekrutacji."
        density="compact"
      />

      <div className="max-w-md">
        <Input
          leadingIcon={<Search className="h-4 w-4" />}
          placeholder="Kandydat, klient, stanowisko albo nazwa pliku…"
          aria-label="Szukaj w moich CV"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      {viewState === "loading" ? (
        <p className="text-sm text-muted-foreground">Ładowanie…</p>
      ) : viewState === "empty" ? (
        <EmptyState
          icon={FileText}
          title={q ? "Nic nie pasuje do wyszukiwania" : "Nie masz jeszcze wygenerowanych CV"}
          description={
            q
              ? "Zmień frazę albo wyczyść pole szukania."
              : "CV generujesz w rekrutacji: karta „CV do klienta” w panelu osoby albo „Generuj CV” w profilu kandydata."
          }
        />
      ) : viewState !== "ready" ? (
        <QueryStateNotice
          state={viewState}
          description={
            viewState === "error"
              ? apiErrorMessage(query.error, "Nie udało się wczytać Twoich CV.")
              : undefined
          }
          onRetry={() => void query.refetch()}
        />
      ) : (
        <div className="relative overflow-x-auto rounded-lg border border-border bg-card">
          <table className="w-full min-w-[820px] text-sm" data-testid="my-generated-cvs">
            <thead className="border-b border-border text-left text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th scope="col" className="sticky left-0 bg-card px-3 py-2 font-medium">
                  Data
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Kandydat
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Rekrutacja
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Plik
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  <span className="sr-only">Akcje</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {items.map((item) => (
                <tr key={item.id} data-testid={`my-cv-row-${item.id}`}>
                  <td className="sticky left-0 whitespace-nowrap bg-card px-3 py-2.5 tabular-nums text-muted-foreground">
                    {formatCvDate(item.created_at)}
                  </td>
                  <td className="px-3 py-2.5">
                    {item.candidate_id != null ? (
                      <Link
                        href={`/candidates/${item.candidate_id}`}
                        className="font-medium text-foreground hover:text-primary hover:underline"
                      >
                        {item.candidate_name}
                      </Link>
                    ) : (
                      <span className="font-medium text-foreground">{item.candidate_name}</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    {item.job_id != null ? (
                      <Link
                        href={
                          item.candidate_id != null
                            ? `/jobs/${item.job_id}?candidate=${item.candidate_id}`
                            : `/jobs/${item.job_id}`
                        }
                        className="block max-w-[18rem] truncate text-foreground hover:text-primary hover:underline"
                        title={item.job_title ?? undefined}
                      >
                        {item.job_title || `Rekrutacja #${item.job_id}`}
                      </Link>
                    ) : (
                      <span className="text-muted-foreground">bez rekrutacji</span>
                    )}
                    {item.client_name ? (
                      <span className="block text-xs text-muted-foreground">{item.client_name}</span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2.5">
                    {/* Nazwa pliku otwiera podgląd — jak w plikach kandydata; przy 1280 px
                        osobny „Podgląd” wypychał „Pobierz” poza ekran. */}
                    {canOpen(item) ? (
                      <button
                        type="button"
                        onClick={() => setPreviewItem(item)}
                        title={`Podgląd: ${item.filename}`}
                        aria-label={`Podgląd CV: ${item.candidate_name}`}
                        className="block max-w-[16rem] truncate text-left font-medium text-foreground hover:text-primary hover:underline"
                      >
                        {item.filename}
                      </button>
                    ) : (
                      <span className="block max-w-[16rem] truncate" title={item.filename}>
                        {item.filename}
                      </span>
                    )}
                    <span
                      className={
                        item.status === "failed"
                          ? "block text-xs text-destructive"
                          : "block text-xs text-muted-foreground"
                      }
                      title={item.status === "failed" ? item.error_message ?? undefined : undefined}
                    >
                      {[myCvState(item), item.language?.toUpperCase()].filter(Boolean).join(" · ")}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-right">
                    {canOpen(item) ? (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => void download(item)}
                        aria-label={`Pobierz CV: ${item.candidate_name}`}
                      >
                        Pobierz
                      </Button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {query.hasNextPage ? (
            <div className="border-t border-border px-3 py-2">
              <Button
                size="sm"
                variant="ghost"
                disabled={query.isFetchingNextPage}
                onClick={() => void query.fetchNextPage()}
              >
                {query.isFetchingNextPage ? "Wczytuję…" : "Pokaż starsze"}
              </Button>
            </div>
          ) : null}
        </div>
      )}

      <GeneratedCvPreviewModal
        item={previewItem}
        onClose={() => setPreviewItem(null)}
        onDownload={(item) => void download(item)}
        loadDocx={
          previewItem?.stage_cv_stage_id != null
            ? (item) => fetchStageCvFile(item.stage_cv_stage_id as number).then((file) => file.blob)
            : undefined
        }
      />
    </div>
  );
}
