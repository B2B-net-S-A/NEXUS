"use client";

/**
 * Podgląd TYLKO DO ODCZYTU dla sekcji „CV" panelu osoby.
 *
 * Warsztat (`CvHandoffWorkbench`) prowadzi osobę stojącą na SWOIM etapie.
 * Osoba, która poszła dalej, ma jednak wysłane CV — dok kanbana pozwalał je
 * otworzyć z dowolnego etapu, więc panel nie może w tym miejscu mówić
 * „dostępne na etapie X". Zapisany screening pokazuje od 09.10.2026 wspólny
 * widok `ScreeningSummaryView` (ten plik miał wcześniej `SavedScreeningView`).
 *
 * Te same trasy i te same klucze zapytań co dok kanbana
 * (`PipelineCandidateDock`): odpowiedź jest wspólna dla obu widoków.
 */

import { CV_CLIENT_LINKS_UI_ENABLED } from "@/lib/cv-generator";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileText, Loader2 } from "lucide-react";

import {
  candidateStageCvApi,
  type CVOriginalSnapshot,
  type CVShareTokensForRecruitment,
  type CVShareTokenListItem,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CVOriginalPreviewModal } from "@/components/v2/modals/CVOriginalPreviewModal";
import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import { formatDate } from "@/lib/utils";

function LoadError({ what, onRetry }: { what: string; onRetry: () => void }) {
  // Awaria NIE może wyglądać jak „nic nie zapisano".
  return (
    <p role="alert" className="text-xs text-destructive-muted-foreground">
      Nie udało się wczytać: {what}.{" "}
      <button type="button" className="font-medium underline underline-offset-2" onClick={onRetry}>
        Ponów
      </button>
    </p>
  );
}

function linkState(link: CVShareTokenListItem): string {
  if (link.revoked) return "odwołany";
  if (link.expires_at && new Date(link.expires_at).getTime() < Date.now()) return "wygasł";
  return "aktywny";
}

/** Wersje CV i linki dla klienta osoby, która nie stoi już na „Zweryfikowany". */
export function SavedCvView({
  item,
  stageLabel,
  candidateName,
  jobTitle,
  jobId,
}: {
  item: KanbanItem;
  stageLabel: string;
  candidateName: string;
  jobTitle: string;
  jobId: number;
}) {
  const [openOriginal, setOpenOriginal] = useState(false);
  const original = useQuery<CVOriginalSnapshot>({
    queryKey: ["cv-original", item.id],
    queryFn: () => candidateStageCvApi.original.get(item.id).then((r) => r.data),
  });
  // Linki ORAZ stan CV firmowego z CAŁEJ pary (kandydat, rekrutacja), nie
  // z bieżącego etapu: link i sfinalizowane CV leżą na etapie SPRZED ruchu na
  // „CV Wysłane", więc odczyt per etap mówił tu „brak", choć klient miał
  // działający link do gotowego CV. (Odczyt per etap dodatkowo ZAKŁADA szkic
  // CV firmowego na bieżącym etapie — podgląd tylko do odczytu nie może pisać.)
  const pair = useQuery<CVShareTokensForRecruitment>({
    queryKey: ["cv-share-tokens-recruitment", item.candidate_id, jobId],
    queryFn: () =>
      candidateStageCvApi.share
        .listForRecruitment(item.candidate_id, jobId)
        .then((r) => r.data),
  });
  const links = pair.data?.items ?? [];
  const brandedCv = pair.data?.branded_cv;
  const brandedStage = brandedCv?.stage_name ? ` · etap: ${brandedCv.stage_name}` : "";

  return (
    <section aria-label="CV i linki" className="space-y-3 text-[13px]">
      <p className="text-xs text-muted-foreground">
        Ta osoba jest dziś na etapie „{stageLabel}” — {CV_CLIENT_LINKS_UI_ENABLED ? "CV i linki są" : "CV jest"} tylko do odczytu. Nową wersję
        przygotujesz w generatorze CV na profilu kandydata.
      </p>

      <div className="flex flex-wrap items-center gap-1.5">
        {original.isLoading || pair.isLoading ? (
          <Loader2 className="size-3 animate-spin text-muted-foreground" aria-hidden />
        ) : null}
        {original.data ? (
          original.data.has_snapshot ? (
            <Badge size="sm" variant="success">CV oryginalne</Badge>
          ) : (
            <Badge size="sm" variant="warning">Brak CV w momencie zgłoszenia</Badge>
          )
        ) : null}
        {brandedCv ? (
          brandedCv.status === "finalized" ? (
            <Badge
              size="sm"
              variant="success"
              title={
                brandedCv.finalized_at
                  ? `Zatwierdzone ${formatDate(brandedCv.finalized_at)}`
                  : undefined
              }
            >
              {`CV do klienta: gotowe${brandedStage}`}
            </Badge>
          ) : brandedCv.status === "draft" ? (
            <Badge size="sm" variant="info">{`CV do klienta: szkic${brandedStage}`}</Badge>
          ) : (
            <Badge size="sm" variant="neutral">CV do klienta: brak</Badge>
          )
        ) : null}
      </div>
      {original.isError ? (
        <LoadError what="CV oryginalne" onRetry={() => void original.refetch()} />
      ) : null}

      <Button size="sm" variant="outline" className="justify-start" onClick={() => setOpenOriginal(true)}>
        <FileText className="size-3.5" aria-hidden /> Pokaż CV oryginalne
      </Button>

      {CV_CLIENT_LINKS_UI_ENABLED ? (
      <div className="space-y-1.5">
        <h4 className="text-xs font-semibold text-muted-foreground">Linki dla klienta</h4>
        {pair.isLoading ? (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" aria-hidden /> Wczytywanie…
          </p>
        ) : pair.isError ? (
          <LoadError what="CV do klienta i linki dla klienta" onRetry={() => void pair.refetch()} />
        ) : pair.isSuccess && links.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            W tej rekrutacji nie utworzono jeszcze linku dla klienta do CV tej osoby.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {links.map((link) => (
              <li
                key={link.revoke_key}
                className="rounded-md border border-border bg-muted/20 px-2.5 py-1.5 text-xs"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-foreground">{link.token_preview}</span>
                  <span className="text-muted-foreground">{linkState(link)}</span>
                </div>
                <div className="text-muted-foreground">
                  {`etap: ${link.stage_name} · `}
                  {link.created_at ? `utworzony ${formatDate(link.created_at)}` : "data nieznana"}
                  {link.created_by_name ? ` · ${link.created_by_name}` : ""}
                  {` · wyświetlenia: ${link.view_count}`}
                  {link.max_views ? ` z ${link.max_views}` : ""}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
      ) : null}

      {openOriginal ? (
        <CVOriginalPreviewModal
          open
          onOpenChange={setOpenOriginal}
          stageId={item.id}
          jobTitle={jobTitle}
          candidateName={candidateName}
        />
      ) : null}
    </section>
  );
}
