"use client";

/**
 * „Profil Championa” w czterech zakładkach (decyzje Artura 04.10.2026,
 * makieta https://claude.ai/artifact/FwQr2uYhWcRfdDeWdbStUc).
 *
 * Do 04.10.2026 widok „Zlecenie i Champion” był jedną stroną (ok. 5 000 px
 * w „Podglądzie”, 51 pól w „Edytuj”) z panelem „Gotowość” obok. Teraz:
 *  - Brief — to, co rekruter musi wiedzieć przed telefonem, i pasek
 *    „Do dopięcia” dla Delivery Leada,
 *  - Technologie po ludzku — słowniczek i rola z biblioteki,
 *  - Klient i historia — karta klienta, pytania z rozmów, wcześniejsze zapytania,
 *  - Zespół i ogłoszenie — dawne zakładki panelu bocznego.
 *
 * „Edytuj” przy bloku otwiera szufladę z sekcjami tego bloku. Pełny formularz
 * („Wypełnij szybciej”, import, uzgadnianie) jest pod „⋯ → Edytuj cały
 * Profil Championa” (`?mode=edit`, renderuje go strona).
 */

import { useEffect, useState } from "react";

import { ChampionBriefView, type ChampionBriefJob } from "@/components/champion/ChampionBriefView";
import { ChampionClientTab } from "@/components/champion/ChampionClientTab";
import { ChampionEditDrawer } from "@/components/champion/ChampionEditDrawer";
import { ChampionTodoStrip, type ChampionTodoJob } from "@/components/champion/ChampionTodoStrip";
import { PlainBriefBlock } from "@/components/champion/plain/PlainBriefBlock";
import { TabbedNav } from "@/components/ds";
import { JobAnnouncementSection } from "@/components/v2/jobs/JobAnnouncementSection";
import { JobTeamTab, type JobTeamTabJob } from "@/components/v2/jobs/JobReadinessDock";
import { usePlainBrief } from "@/lib/api/plainKnowledge";
import {
  CHAMPION_BLOCKS,
  CHAMPION_TABS,
  blockForAnchor,
  type ChampionBlock,
  type ChampionTab,
} from "@/lib/champion-blocks";
import { CHAMPION_SECTIONS } from "@/lib/champion-section-state";
import { readyGlossaryCount } from "@/lib/plain-glossary-lookup";

const CHAMPION_SECTION_ANCHOR = Object.fromEntries(
  CHAMPION_SECTIONS.map((section) => [section.id, section.anchor]),
) as Record<(typeof CHAMPION_SECTIONS)[number]["id"], string>;

export type ChampionWorkspaceJob = ChampionBriefJob &
  JobTeamTabJob &
  ChampionTodoJob & { status?: string | null };

export interface ChampionWorkspaceProps {
  jobId: number;
  job: ChampionWorkspaceJob;
  tab: ChampionTab;
  onTabChange: (tab: ChampionTab) => void;
  /**
   * Szuflada edycji bloku sterowana ze strony (okno „Kandydaci do dodania”
   * otwiera „Czego szukamy”). Brak = stan lokalny.
   */
  editBlock?: ChampionBlock | null;
  onEditBlockChange?: (block: ChampionBlock | null) => void;
  /**
   * Pełny formularz (ukryty po „Wróć do Profilu Championa”) ma niezapisane
   * zmiany. Zapis z szuflady odświeża profil, a to kasowałoby jego szkic —
   * wtedy „Edytuj” przy bloku prowadzi do pełnego formularza.
   */
  fullFormDirty?: boolean;
  canEditChampion: boolean;
  /** Zapis weryfikacji i briefingu (serwer: admin albo Delivery Lead). */
  canVerifyChampion?: boolean;
  canWritePipeline: boolean;
  /** Uprawnienie do prowadzenia rekrutacji — pasek „Do dopięcia”. */
  canSeeGate: boolean;
  /** Pełna edycja rekrutacji (`job.update`). */
  canEditJob: boolean;
  /** Jakakolwiek edycja rekrutacji — portale nie tylko do odczytu. */
  canEditJobContent: boolean;
  onEditJob: () => void;
  /** Pełny formularz (`?mode=edit`), opcjonalnie z kotwicą sekcji. */
  onEditFull: (anchor?: string | null) => void;
  onOpenManualSearch?: () => void;
  onWriteAnnouncement?: () => void;
  onGenerateInviteLink?: () => void;
  portalsFocus?: boolean;
}

export function ChampionWorkspace({
  jobId,
  job,
  tab,
  onTabChange,
  editBlock: editBlockProp,
  onEditBlockChange,
  fullFormDirty = false,
  canEditChampion,
  canVerifyChampion,
  canWritePipeline,
  canSeeGate,
  canEditJob,
  canEditJobContent,
  onEditJob,
  onEditFull,
  onOpenManualSearch,
  onWriteAnnouncement,
  onGenerateInviteLink,
  portalsFocus = false,
}: ChampionWorkspaceProps) {
  const [localEditBlock, setLocalEditBlock] = useState<ChampionBlock | null>(null);
  const controlled = onEditBlockChange !== undefined;
  const editBlock = controlled ? (editBlockProp ?? null) : localEditBlock;
  const setEditBlock = controlled ? onEditBlockChange : setLocalEditBlock;
  const plainQuery = usePlainBrief(jobId);
  const glossaryCount = readyGlossaryCount(plainQuery.data?.glossary);
  const openBlock = (block: ChampionBlock) => {
    if (fullFormDirty) {
      onEditFull(CHAMPION_SECTION_ANCHOR[CHAMPION_BLOCKS[block].sections[0]]);
      return;
    }
    setEditBlock(block);
  };
  const onEditBlock = canEditChampion ? openBlock : undefined;
  // Szuflada zlecona przez stronę (okno „Kandydaci do dodania”) przy
  // niezapisanym pełnym formularzu też idzie do formularza.
  useEffect(() => {
    if (!fullFormDirty || !editBlock) return;
    setEditBlock(null);
    onEditFull(CHAMPION_SECTION_ANCHOR[CHAMPION_BLOCKS[editBlock].sections[0]]);
  }, [fullFormDirty, editBlock, setEditBlock, onEditFull]);
  // Brak z bramki gotowości wskazuje sekcję edytora — otwieramy jej blok,
  // a gdy kotwica nie ma bloku (np. tytuł, klient), pełny formularz.
  const goChampion = (anchor: string | null) => {
    const block = blockForAnchor(anchor);
    if (block && canEditChampion) openBlock(block);
    else onEditFull(anchor);
  };

  return (
    <div className="space-y-3.5" data-testid="champion-workspace">
      <div data-help="job.champion.tabs">
        <TabbedNav
          ariaLabel="Profil Championa"
          value={tab}
          onValueChange={(value) => onTabChange(value as ChampionTab)}
          tabs={CHAMPION_TABS.map((t) =>
            t.value === "tech" && glossaryCount > 0 ? { ...t, count: glossaryCount } : t,
          )}
          overflow="scroll"
        />
      </div>

      {tab === "brief" ? (
        <div className="space-y-3.5" data-testid="champion-tab-brief">
          <ChampionTodoStrip
            jobId={jobId}
            job={job}
            canSeeGate={canSeeGate}
            canWritePipeline={canWritePipeline}
            canEditChampion={canEditChampion}
            canVerifyChampion={canVerifyChampion}
            canEditJob={canEditJob}
            onGoChampion={goChampion}
            onEditJob={onEditJob}
          />
          <ChampionBriefView
            jobId={jobId}
            job={job}
            onEditBlock={onEditBlock}
            onOpenManualSearch={onOpenManualSearch}
            onOpenTeam={() => onTabChange("team")}
            onOpenClient={() => onTabChange("client")}
          />
        </div>
      ) : null}

      {tab === "tech" ? (
        <div className="max-w-5xl" data-testid="champion-tab-tech">
          <PlainBriefBlock jobId={jobId} parts="knowledge" />
        </div>
      ) : null}

      {tab === "client" ? (
        <ChampionClientTab
          jobId={jobId}
          clientId={job.client_id ?? null}
          onEditBlock={onEditBlock}
          requestHistoryReadOnly={!canWritePipeline}
        />
      ) : null}

      {tab === "team" ? (
        <div
          className="grid grid-cols-1 gap-3.5 xl:grid-cols-2"
          data-testid="champion-tab-team"
        >
          <section className="min-w-0 rounded-xl border border-border bg-card px-4 py-3.5" aria-label="Zespół">
            <h2 className="mb-3 text-[14px] font-semibold text-foreground">Zespół</h2>
            <JobTeamTab jobId={jobId} job={job} />
          </section>
          <section
            className="min-w-0 rounded-xl border border-border bg-card px-4 py-3.5"
            aria-label="Ogłoszenie"
          >
            <h2 className="mb-3 text-[14px] font-semibold text-foreground">Ogłoszenie</h2>
            <JobAnnouncementSection
              jobId={jobId}
              jobStatus={job.status}
              onWriteAnnouncement={onWriteAnnouncement}
              onGenerateInviteLink={onGenerateInviteLink}
              readOnly={!canEditJobContent}
              portalsFocus={portalsFocus}
            />
          </section>
        </div>
      ) : null}

      <ChampionEditDrawer
        jobId={jobId}
        clientId={job.client_id ?? null}
        block={canEditChampion && !fullFormDirty ? editBlock : null}
        canEdit={canEditChampion}
        onClose={() => setEditBlock(null)}
      />
    </div>
  );
}
