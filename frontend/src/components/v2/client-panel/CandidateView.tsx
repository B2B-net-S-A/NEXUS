"use client";

/**
 * Widok jednej osoby: nagłówek z liczbami, zakładki i pasek akcji. Zmiana osoby
 * strzałkami remontuje komponent (`key` u rodzica), a zakładka wraca do pierwszej.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  panelCandidateKey,
  type PanelCandidate,
  type PanelView,
} from "@/lib/api/clientPanel";

import { EvidenceTab } from "./EvidenceTab";
import { FilesTab } from "./FilesTab";
import { AskDialog, NotFitDialog, SlotsDialog } from "./PanelDialogs";
import { TalkTab, clientQuestions, interviewOpen } from "./TalkTab";
import { TermsTab } from "./TermsTab";
import { usePanelContext } from "./panel-context";
import { formatRate, questionFromHint } from "./panel-logic";
import { PanelRetry, PanelTabs, StatePill } from "./parts";

type CandidateTab = "fit" | "terms" | "files" | "talk";
type Dialog = { kind: "ask"; prefill: string } | { kind: "slots" } | { kind: "not-fit" } | null;

function Fact({ value, label }: { value: string; label: string }) {
  return (
    <div className="min-w-[64px]">
      <div className="text-sm font-semibold tabular-nums">{value}</div>
      <div className="text-[11.5px] text-muted-foreground">{label}</div>
    </div>
  );
}

export function CandidateView({
  view,
  candidate,
  onBack,
  onOpen,
}: {
  view: PanelView;
  candidate: PanelCandidate;
  onBack: () => void;
  onOpen: (publicId: string) => void;
}) {
  const { token, transport } = usePanelContext();
  const [tab, setTabState] = useState<CandidateTab>("fit");
  const [dialog, setDialog] = useState<Dialog>(null);
  const { requirements, candidates, panel } = view;
  const position = candidates.findIndex((item) => item.public_id === candidate.public_id);
  const publicId = candidate.public_id;

  const detailQuery = useQuery({
    queryKey: panelCandidateKey(token, publicId),
    queryFn: () => transport.fetchCandidate(publicId),
    staleTime: 30_000,
  });
  const detail = detailQuery.data ?? null;

  const threadCount = detail ? clientQuestions(detail).length : 0;
  const tabs = [
    { id: "fit", label: "Dopasowanie do wymagań" },
    { id: "terms", label: "Warunki" },
    { id: "files", label: "Pliki" },
    { id: "talk", label: threadCount > 0 ? `Pytania i rozmowa (${threadCount})` : "Pytania i rozmowa" },
  ] as const;

  // Wejście na osobę i pobranie pliku serwer zapisuje sam przy odczycie, więc
  // zdarzenia idą tylko za to, czego z odczytu nie widać.
  const setTab = (next: CandidateTab) => {
    setTabState(next);
    transport.sendEvent({
      public_id: publicId,
      action: "tab",
      detail: tabs.find((item) => item.id === next)?.label.slice(0, 120),
    });
  };

  const rate = panel.show_rate ? formatRate(candidate.rate) : null;
  const ask = (prefill = "") => setDialog({ kind: "ask", prefill });
  const interviewBusy = detail ? interviewOpen(detail.interview.status) : false;

  return (
    <>
      <main className="flex min-h-0 flex-1 flex-col overflow-auto px-4 pt-3" data-testid="client-panel-candidate">
        <div className="mb-2 flex shrink-0 flex-wrap items-center gap-x-3.5 gap-y-2">
          <Button variant="outline" size="sm" onClick={onBack}>
            <ChevronLeft className="h-3.5 w-3.5" />
            Wszyscy ({candidates.length})
          </Button>
          <div className="min-w-0">
            <h1 className="font-display text-lg font-bold tracking-tight">{candidate.name}</h1>
            <p className="text-xs text-muted-foreground">
              {[candidate.title, candidate.city].filter(Boolean).join(" · ")}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 sm:ml-auto">
            <Fact value={`${candidate.in_projects} z ${requirements.length}`} label="w projektach" />
            <Fact value={String(candidate.missing)} label="brak w CV" />
            {rate ? <Fact value={rate} label="stawka netto" /> : null}
            <Fact value={candidate.available_label} label="dostępność" />
            {candidates.length > 1 ? (
              <div className="flex items-center gap-1">
                <Button
                  variant="outline"
                  size="icon-sm"
                  disabled={position <= 0}
                  aria-label="Poprzedni kandydat"
                  onClick={() => onOpen(candidates[position - 1].public_id)}
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                </Button>
                <span className="text-xs tabular-nums text-muted-foreground">
                  {position + 1}/{candidates.length}
                </span>
                <Button
                  variant="outline"
                  size="icon-sm"
                  disabled={position >= candidates.length - 1}
                  aria-label="Następny kandydat"
                  onClick={() => onOpen(candidates[position + 1].public_id)}
                >
                  <ChevronRight className="h-3.5 w-3.5" />
                </Button>
              </div>
            ) : null}
          </div>
        </div>

        <PanelTabs tabs={tabs} active={tab} onChange={setTab} label="Widok kandydata" />

        <div className="flex flex-col pb-2.5 md:min-h-0 md:flex-1">
          {detailQuery.isError ? (
            <PanelRetry
              text="Nie udało się wczytać danych tej osoby. To nie znaczy, że ich nie ma."
              onRetry={() => void detailQuery.refetch()}
            />
          ) : !detail ? (
            <div className="p-4 text-sm text-muted-foreground" role="status">
              Wczytuję dane osoby…
            </div>
          ) : tab === "fit" ? (
            <EvidenceTab
              requirements={requirements}
              candidate={candidate}
              detail={detail}
              allowActions={panel.allow_actions}
              onAsk={(label) => ask(questionFromHint(label))}
            />
          ) : tab === "terms" ? (
            <TermsTab view={view} candidate={candidate} detail={detail} />
          ) : tab === "files" ? (
            <FilesTab
              candidate={candidate}
              detail={detail}
              allowActions={panel.allow_actions}
              onAskForFile={() => ask("Czy kandydat może dosłać certyfikat albo inny dokument?")}
            />
          ) : (
            <TalkTab
              detail={detail}
              allowActions={panel.allow_actions}
              ownerName={view.owner?.name ?? null}
              onAsk={() => ask()}
              onRequestInterview={() => setDialog({ kind: "slots" })}
            />
          )}
        </div>
      </main>

      <footer className="flex shrink-0 flex-wrap items-center gap-2 border-t border-border bg-card px-4 py-2">
        <div className="mr-auto">
          <StatePill state={candidate.state} />
        </div>
        {panel.allow_actions ? (
          <>
            <Button
              variant="outline"
              disabled={candidate.state === "not_fit"}
              onClick={() => setDialog({ kind: "not-fit" })}
            >
              Nie pasuje
            </Button>
            <Button variant="outline" onClick={() => ask()}>
              Zapytaj o kandydata
            </Button>
            <Button
              disabled={interviewBusy}
              title={interviewBusy ? "Terminy są już u opiekuna procesu." : undefined}
              onClick={() => setDialog({ kind: "slots" })}
            >
              Poproś o rozmowę
            </Button>
          </>
        ) : null}
      </footer>

      {dialog?.kind === "ask" ? (
        <AskDialog
          view={view}
          candidate={candidate}
          prefill={dialog.prefill}
          onClose={() => setDialog(null)}
          onSent={() => setTabState("talk")}
        />
      ) : null}
      {dialog?.kind === "not-fit" ? (
        <NotFitDialog view={view} candidate={candidate} onClose={() => setDialog(null)} />
      ) : null}
      {dialog?.kind === "slots" ? (
        <SlotsDialog
          candidate={candidate}
          onClose={() => setDialog(null)}
          onSent={() => setTabState("talk")}
        />
      ) : null}
    </>
  );
}
