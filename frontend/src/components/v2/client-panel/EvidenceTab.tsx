"use client";

/**
 * Dopasowanie: wymagania i cytaty po lewej, CV po prawej. Klik w dowód szuka
 * w PDF-ie frazy cytatu, a gdy jej nie ma (podział wiersza, inne znaki), samego
 * słowa. Podświetlenie robi `PdfDocumentViewer`; pdf.js ładuje się dopiero tu,
 * dlatego przeglądarka jest importowana dynamicznie i nie obciąża listy.
 *
 * Brak CV (`cv.available=false`) nie zabiera wymagań ani cytatów.
 */

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, Download } from "lucide-react";

import { Button } from "@/components/ui/button";
import type {
  DocumentFindResult,
  DocumentTextAvailability,
} from "@/components/v2/files/DocumentSearchBar";
import {
  panelCvKey,
  type EvidenceItem,
  type PanelCandidate,
  type PanelCandidateDetail,
  type PanelRequirement,
  type RequirementStatus,
} from "@/lib/api/clientPanel";
import { cn } from "@/lib/utils";

import { usePanelContext } from "./panel-context";
import {
  STATUS_GROUPS,
  evidenceFallback,
  formatPanelDate,
  startEvidenceSearch,
  type EvidenceSearch,
} from "./panel-logic";
import { PANEL_CARD, PanelRetry, StatusDot } from "./parts";

// Sam typ: zwykły `import type` wyglądałby dla strażnika paczek jak import przeglądarki.
type PdfViewerHandle = import("@/components/v2/files/PdfDocumentViewer").PdfViewerHandle;

const PdfDocumentViewer = dynamic(
  () => import("@/components/v2/files/PdfDocumentViewer").then((mod) => mod.PdfDocumentViewer),
  { ssr: false },
);

const QUOTE_PREVIEW = 92;
const EVIDENCE_SHOWN = 4;
const NO_RESULT: DocumentFindResult = { current: 0, total: 0, pending: false };

function statusOf(
  key: string,
  candidate: PanelCandidate,
  detail: PanelCandidateDetail,
): RequirementStatus {
  return detail.evidence[key]?.status ?? candidate.statuses[key] ?? "none";
}

/** Pierwsze wymaganie z projektów: tam dowód jest najmocniejszy. */
function firstRequirement(
  requirements: readonly PanelRequirement[],
  candidate: PanelCandidate,
  detail: PanelCandidateDetail,
): string | null {
  const inProject = requirements.find(
    (item) => statusOf(item.key, candidate, detail) === "project",
  );
  return (inProject ?? requirements[0])?.key ?? null;
}

function CvPane({
  candidate,
  detail,
  item,
}: {
  candidate: PanelCandidate;
  detail: PanelCandidateDetail;
  item: EvidenceItem | null;
}) {
  const { token, transport } = usePanelContext();
  const handleRef = useRef<PdfViewerHandle | null>(null);
  const searchRef = useRef<EvidenceSearch | null>(null);
  const itemRef = useRef(item);
  itemRef.current = item;
  const [result, setResult] = useState<DocumentFindResult>(NO_RESULT);
  const [viewerFailed, setViewerFailed] = useState(false);
  const [availability, setAvailability] = useState<DocumentTextAvailability>("pending");

  const { cv } = detail;
  const cvUrl = cv.available ? cv.url : null;
  const fileQuery = useQuery({
    queryKey: panelCvKey(token, candidate.public_id),
    queryFn: () => transport.fetchCv(cvUrl as string),
    enabled: cvUrl != null,
    staleTime: Infinity,
  });

  const runSearch = useCallback(() => {
    const current = itemRef.current;
    searchRef.current = current ? startEvidenceSearch(current) : null;
    if (current) setResult({ current: 0, total: 0, pending: true });
    else setResult(NO_RESULT);
    handleRef.current?.search(current?.quote ?? "");
  }, []);

  useEffect(() => {
    runSearch();
  }, [item, runSearch]);

  const onFindResult = useCallback((next: DocumentFindResult) => {
    const fallback = evidenceFallback(searchRef.current, next);
    if (fallback && searchRef.current) {
      searchRef.current = { ...searchRef.current, stage: "term" };
      setResult({ current: 0, total: 0, pending: true });
      handleRef.current?.search(fallback);
      return;
    }
    setResult(next);
  }, []);

  return (
    <div className={cn(PANEL_CARD, "flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden")}>
      <div className="flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1 border-b border-border px-2.5 py-1.5 text-xs text-muted-foreground">
        <span className="font-semibold text-foreground">
          {candidate.sent_at ? `CV przesłane ${formatPanelDate(candidate.sent_at)}` : "Przesłane CV"}
        </span>
        <span>ten sam plik, który dostaliście</span>
        <span className="flex items-center gap-1 sm:ml-auto" aria-live="polite" data-testid="cv-find-result">
          {!cvUrl || viewerFailed
            ? null
            : !item
              ? "Wybierz wymaganie"
              : availability === "no_text"
                ? "Plik bez warstwy tekstu, cytat bez podświetlenia"
                : result.pending
                  ? "Szukam…"
                  : result.total > 0
                    ? `Znaleziono: ${result.total}`
                    : "Nie ma tej frazy w podglądzie"}
          {result.total > 1 && !result.pending ? (
            <>
              <button
                type="button"
                aria-label="Poprzednie trafienie"
                className="hit-area rounded p-0.5 hover:bg-muted"
                onClick={() => handleRef.current?.step(true)}
              >
                <ChevronUp className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                aria-label="Następne trafienie"
                className="hit-area rounded p-0.5 hover:bg-muted"
                onClick={() => handleRef.current?.step(false)}
              >
                <ChevronDown className="h-3.5 w-3.5" />
              </button>
            </>
          ) : null}
        </span>
        {cvUrl ? (
          <Button asChild variant="outline" size="sm">
            <a
              href={transport.fileHref(cvUrl)}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() =>
                transport.sendEvent({ public_id: candidate.public_id, action: "file", detail: "CV" })
              }
            >
              <Download className="h-3.5 w-3.5" />
              Pobierz plik
            </a>
          </Button>
        ) : null}
      </div>
      <div className="relative min-h-0 flex-1 bg-muted" data-testid="cv-pane">
        {!cvUrl ? (
          <div className="p-4 text-sm text-muted-foreground" data-testid="cv-unavailable">
            Podglądu tego CV nie ma w panelu. Wymagania i cytaty po lewej pochodzą z pliku, który
            dostaliście, a opiekun procesu prześle go ponownie na prośbę.
          </div>
        ) : fileQuery.isError || viewerFailed ? (
          <div className="p-3">
            <PanelRetry
              text="Nie udało się wczytać podglądu CV. Wymagania i cytaty po lewej działają dalej."
              onRetry={() => {
                setViewerFailed(false);
                void fileQuery.refetch();
              }}
            />
          </div>
        ) : fileQuery.data ? (
          <PdfDocumentViewer
            file={fileQuery.data}
            fit="auto"
            handleRef={handleRef}
            onLoaded={runSearch}
            onError={() => setViewerFailed(true)}
            onFindResult={onFindResult}
            onTextAvailability={setAvailability}
          />
        ) : (
          <div className="p-4 text-sm text-muted-foreground" role="status">
            Wczytuję CV…
          </div>
        )}
      </div>
    </div>
  );
}

export function EvidenceTab({
  requirements,
  candidate,
  detail,
  allowActions,
  onAsk,
}: {
  requirements: readonly PanelRequirement[];
  candidate: PanelCandidate;
  detail: PanelCandidateDetail;
  allowActions: boolean;
  onAsk: (label: string) => void;
}) {
  const { transport } = usePanelContext();
  const [selected, setSelected] = useState(() =>
    firstRequirement(requirements, candidate, detail),
  );
  const [evidenceIndex, setEvidenceIndex] = useState(0);
  const items = selected ? (detail.evidence[selected]?.items ?? []) : [];
  const currentItem = items[evidenceIndex] ?? null;

  const select = (requirement: PanelRequirement) => {
    setSelected(requirement.key);
    setEvidenceIndex(0);
    transport.sendEvent({
      public_id: candidate.public_id,
      action: "requirement",
      detail: requirement.label.slice(0, 120),
    });
  };

  return (
    <div className="grid gap-2.5 md:min-h-0 md:flex-1 md:grid-cols-[370px_minmax(0,1fr)] md:grid-rows-1">
      <div className={cn(PANEL_CARD, "max-h-80 overflow-auto p-1 md:max-h-none")} data-testid="requirements-list">
        {STATUS_GROUPS.map(({ status, title }) => {
          const rows = requirements.filter(
            (item) => statusOf(item.key, candidate, detail) === status,
          );
          if (rows.length === 0) return null;
          return (
            <section key={status}>
              <h2 className="px-2 pb-0.5 pt-2 text-[11px] uppercase tracking-wider text-muted-foreground">
                {title} · {rows.length}
              </h2>
              {rows.map((requirement) => {
                const on = selected === requirement.key;
                const rowItems = detail.evidence[requirement.key]?.items ?? [];
                const first = rowItems[0];
                const where =
                  status === "project" ? first?.where : status === "list" ? "lista" : null;
                return (
                  <div key={requirement.key}>
                    <button
                      type="button"
                      aria-expanded={on}
                      onClick={() => select(requirement)}
                      className={cn(
                        "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm",
                        "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
                        on ? "bg-primary/10" : "hover:bg-muted",
                      )}
                    >
                      <StatusDot status={status} />
                      <span className="min-w-0 flex-1 font-medium">{requirement.label}</span>
                      {where ? (
                        <span className="max-w-[150px] truncate text-xs text-muted-foreground">
                          {where}
                        </span>
                      ) : null}
                    </button>
                    {on ? (
                      <div className="grid gap-1 pb-1.5 pl-6 pr-1 pt-1">
                        {rowItems.length > 0 ? (
                          rowItems.slice(0, EVIDENCE_SHOWN).map((item, index) => (
                            <button
                              key={`${item.quote}-${index}`}
                              type="button"
                              aria-pressed={evidenceIndex === index}
                              onClick={() => setEvidenceIndex(index)}
                              className={cn(
                                "rounded-md border px-2 py-1 text-left text-xs",
                                evidenceIndex === index
                                  ? "border-warning bg-warning-muted text-warning-muted-foreground"
                                  : "border-border bg-card hover:bg-muted",
                              )}
                            >
                              {item.quote.length > QUOTE_PREVIEW
                                ? `${item.quote.slice(0, QUOTE_PREVIEW)}…`
                                : item.quote}
                              {item.where ? (
                                <span className="block text-[11.5px] opacity-80">
                                  {item.where}
                                  {item.dates ? `, ${item.dates}` : ""}
                                </span>
                              ) : null}
                            </button>
                          ))
                        ) : (
                          <>
                            <p className="text-xs text-muted-foreground">
                              W tym CV nie ma wzmianki o: {requirement.label}.
                            </p>
                            {allowActions ? (
                              <div>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => onAsk(requirement.label)}
                                >
                                  Zapytaj o to
                                </Button>
                              </div>
                            ) : null}
                          </>
                        )}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </section>
          );
        })}
      </div>
      <div className="flex h-[480px] min-h-0 min-w-0 flex-col md:h-auto">
        <CvPane candidate={candidate} detail={detail} item={currentItem} />
      </div>
    </div>
  );
}
