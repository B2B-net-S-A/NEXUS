"use client";

import type { ReactNode } from "react";
import {
  BookOpen,
  CalendarClock,
  ChevronDown,
  ChevronUp,
  ClipboardCheck,
  Ellipsis,
  FileSignature,
  FileText,
  History,
  LayoutGrid,
  Link2,
  MessageCircle,
  PencilLine,
  Search,
  Sparkles,
  Target,
  UserCheck,
  UserPlus,
  Wand2,
} from "lucide-react";

import { EntityHeader } from "@/components/ds/EntityHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

export type JobDetailTab =
  | "pipeline"
  | "history"
  | "ai-matching"
  | "manual-search"
  | "portals"
  | "champion"
  | "questions"
  | "chat"
  // Kroki 05 i 06 programu „flow w języku C2" (PR 6/7) — NOWE wartości,
  // żadna istniejąca nie jest przepinana (kontrakt wspólny programu).
  | "screening"
  | "cv"
  // Kroki 07 i 08 programu „flow w języku C2" (PR 7/7). Dochodzą jako NOWE
  // wartości — żadna istniejąca zakładka nie jest przepinana.
  | "interviews"
  | "contract";

const SOURCING_TABS = new Set<JobDetailTab>([
  "ai-matching",
  "manual-search",
  "portals",
]);

interface JobDetailCompactHeaderProps {
  title: ReactNode;
  referenceNumber?: string | null;
  badges?: ReactNode;
  metadata?: ReactNode;
  presence?: ReactNode;
  activeTab: JobDetailTab;
  onTabChange: (tab: JobDetailTab) => void;
  onAddCandidate?: () => void;
  onEdit?: () => void;
  onWriteAnnouncement?: () => void;
  onGenerateInviteLink?: () => void;
  chatUnreadCount?: number;
  /** Kandydaci w procesie (kolumny nie-terminalne kanbana). `undefined` = nie
   *  policzono jeszcze (kanban ładuje się na zakładce Pipeline) — listwa nie
   *  pokazuje wtedy liczby, zamiast pokazywać zero. */
  pipelineCount?: number;
  /** Krok 05 — kolejka screeningu (etap „Screening" + oczekujący na akceptację
   *  stawki). `undefined` = jeszcze nie policzono; ta sama zasada co wyżej. */
  screeningCount?: number;
  /** Krok 06 — zweryfikowani czekający na wysyłkę CV do klienta. */
  cvCount?: number;
  /** Kandydaci na etapach zewnętrznych (krok 07). `undefined` = nie policzono. */
  interviewsCount?: number;
  /** Kandydaci na etapach umowy i zatrudnienia (krok 08). `undefined` = nie policzono. */
  contractCount?: number;
  contextOpen: boolean;
  onContextOpenChange: (open: boolean) => void;
  contextContent: ReactNode;
}

function deferMenuAction(action: () => void) {
  window.setTimeout(action, 0);
}

function WorkspaceButton({
  active,
  children,
  className,
  ...props
}: React.ComponentProps<typeof Button> & { active?: boolean }) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      className={cn(
        "h-10 rounded-none border-b-2 px-3 whitespace-nowrap",
        active
          ? "border-primary text-primary"
          : "border-transparent text-muted-foreground",
        className,
      )}
      aria-current={active ? "page" : undefined}
      {...props}
    >
      {children}
    </Button>
  );
}

function CountBadge({ value }: { value: number }) {
  return (
    <Badge
      variant="outline"
      size="sm"
      className="tabular-nums"
      aria-hidden="true"
    >
      {value > 999 ? "999+" : value}
    </Badge>
  );
}

/**
 * Compact, two-row recruitment workspace header.
 *
 * The first row keeps identity and the primary action visible. The second row
 * is the **steps strip** (makieta C2 → „listwa kroków"): sections in the
 * order people actually work — Zlecenie i Champion → Pozyskiwanie → Pipeline
 * → Baza pytań → Rozmowy i decyzja → Umowa — with Historia and Chat on the
 * right and the operational context (team, hiring manager, Priority Work)
 * behind one disclosure. It replaces three earlier entry points (tabs +
 * „Narzędzia ▾" + „Pozyskaj ▾") without dropping a single destination.
 */
export function JobDetailCompactHeader({
  title,
  referenceNumber,
  badges,
  metadata,
  presence,
  activeTab,
  onTabChange,
  onAddCandidate,
  onEdit,
  onWriteAnnouncement,
  onGenerateInviteLink,
  chatUnreadCount = 0,
  pipelineCount,
  screeningCount,
  cvCount,
  interviewsCount,
  contractCount,
  contextOpen,
  onContextOpenChange,
  contextContent,
}: JobDetailCompactHeaderProps) {
  const sourcingActive = SOURCING_TABS.has(activeTab);
  const unreadLabel =
    chatUnreadCount > 0
      ? `Chat, ${chatUnreadCount > 99 ? "ponad 99" : chatUnreadCount} nieprzeczytane`
      : "Chat";

  return (
    <Collapsible open={contextOpen} onOpenChange={onContextOpenChange}>
      <div className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="px-4 py-3">
          <EntityHeader
            density="compact"
            title={title}
            badges={
              referenceNumber || badges ? (
                <>
                  {referenceNumber ? (
                    <Badge
                      variant="outline"
                      className="font-mono"
                      title="Numer referencyjny rekrutacji"
                    >
                      {referenceNumber}
                    </Badge>
                  ) : null}
                  {badges}
                </>
              ) : undefined
            }
            metadata={metadata}
            actions={
              <>
                {presence}
                {onAddCandidate ? (
                  <Button
                    type="button"
                    size="sm"
                    onClick={onAddCandidate}
                    data-testid="open-add-candidates"
                    title="Wyszukaj kandydatów i dodaj ich do pipeline"
                  >
                    <UserPlus className="h-4 w-4" />
                    Dodaj kandydata
                  </Button>
                ) : null}

                {onEdit || onWriteAnnouncement || onGenerateInviteLink ? (
                  <DropdownMenu modal={false}>
                    <DropdownMenuTrigger asChild>
                      <Button
                        type="button"
                        size="icon-sm"
                        variant="outline"
                        aria-label="Więcej akcji rekrutacji"
                        title="Więcej akcji"
                      >
                        <Ellipsis className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-56">
                      <DropdownMenuLabel>Rekrutacja</DropdownMenuLabel>
                      {onEdit ? (
                        <DropdownMenuItem
                          onSelect={() => deferMenuAction(onEdit)}
                        >
                          <PencilLine className="h-4 w-4" />
                          Edytuj
                        </DropdownMenuItem>
                      ) : null}
                      {onWriteAnnouncement ? (
                        <DropdownMenuItem
                          onSelect={() => deferMenuAction(onWriteAnnouncement)}
                        >
                          <Wand2 className="h-4 w-4" />
                          AI Ogłoszenie
                        </DropdownMenuItem>
                      ) : null}
                      {onGenerateInviteLink ? (
                        <>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            onSelect={() =>
                              deferMenuAction(onGenerateInviteLink)
                            }
                          >
                            <Link2 className="h-4 w-4" />
                            Wygeneruj link
                          </DropdownMenuItem>
                        </>
                      ) : null}
                    </DropdownMenuContent>
                  </DropdownMenu>
                ) : null}
              </>
            }
          />
        </div>

        {/* Listwa kroków — kolejność procesu, Historia i Chat po prawej. */}
        <div className="flex min-w-0 items-center justify-between gap-2 border-t border-border px-1">
          <nav
            className="flex min-w-0 items-center overflow-x-auto overscroll-x-contain"
            aria-label="Sekcje rekrutacji"
          >
            <WorkspaceButton
              active={activeTab === "champion"}
              onClick={() => onTabChange("champion")}
              data-testid="tab-champion"
            >
              <PencilLine className="h-4 w-4" />
              Zlecenie i Champion
            </WorkspaceButton>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <WorkspaceButton
                  active={sourcingActive}
                  aria-label="Pozyskaj kandydatów"
                >
                  <Target className="h-4 w-4" />
                  Pozyskiwanie
                  <ChevronDown className="h-3.5 w-3.5 opacity-60" />
                </WorkspaceButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-56">
                <DropdownMenuLabel>Pozyskiwanie</DropdownMenuLabel>
                <DropdownMenuItem
                  aria-current={activeTab === "ai-matching" ? "page" : undefined}
                  onSelect={() => onTabChange("ai-matching")}
                >
                  <Sparkles className="h-4 w-4" />
                  AI Matching
                </DropdownMenuItem>
                <DropdownMenuItem
                  data-testid="tab-manual-search"
                  aria-current={activeTab === "manual-search" ? "page" : undefined}
                  onSelect={() => onTabChange("manual-search")}
                >
                  <Search className="h-4 w-4" />
                  Wyszukaj manualnie
                </DropdownMenuItem>
                <DropdownMenuItem
                  aria-current={activeTab === "portals" ? "page" : undefined}
                  onSelect={() => onTabChange("portals")}
                >
                  <Link2 className="h-4 w-4" />
                  Portale ogłoszeniowe
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>

            <WorkspaceButton
              active={activeTab === "pipeline"}
              onClick={() => onTabChange("pipeline")}
            >
              <LayoutGrid className="h-4 w-4" />
              Pipeline
              {typeof pipelineCount === "number" ? (
                <CountBadge value={pipelineCount} />
              ) : null}
            </WorkspaceButton>

            {/* Krok 05 — stanowisko screeningu (program „flow w języku C2"). */}
            <WorkspaceButton
              active={activeTab === "screening"}
              onClick={() => onTabChange("screening")}
              data-testid="tab-screening"
            >
              <ClipboardCheck className="h-4 w-4" />
              Screening
              {typeof screeningCount === "number" ? (
                <CountBadge value={screeningCount} />
              ) : null}
            </WorkspaceButton>

            {/* Krok 06 — CV do klienta (program „flow w języku C2"). */}
            <WorkspaceButton
              active={activeTab === "cv"}
              onClick={() => onTabChange("cv")}
              data-testid="tab-cv"
            >
              <FileText className="h-4 w-4" />
              CV do klienta
              {typeof cvCount === "number" ? <CountBadge value={cvCount} /> : null}
            </WorkspaceButton>

            <WorkspaceButton
              active={activeTab === "questions"}
              onClick={() => onTabChange("questions")}
              data-testid="tab-questions"
            >
              <BookOpen className="h-4 w-4" />
              Baza pytań
            </WorkspaceButton>

            {/* Kroki 07 i 08 (flow C2, PR 7/7). Liczniki liczy strona z tego
                samego kanbana, którym karmi Pipeline — `undefined` znaczy
                „jeszcze nie policzono", więc listwa nie pokazuje zera zamiast
                niewiedzy (ta sama reguła co `pipelineCount`). */}
            <WorkspaceButton
              active={activeTab === "interviews"}
              onClick={() => onTabChange("interviews")}
              data-testid="tab-interviews"
            >
              <CalendarClock className="h-4 w-4" />
              Rozmowy i decyzja
              {typeof interviewsCount === "number" ? (
                <CountBadge value={interviewsCount} />
              ) : null}
            </WorkspaceButton>

            <WorkspaceButton
              active={activeTab === "contract"}
              onClick={() => onTabChange("contract")}
              data-testid="tab-contract"
            >
              <FileSignature className="h-4 w-4" />
              Umowa
              {typeof contractCount === "number" ? (
                <CountBadge value={contractCount} />
              ) : null}
            </WorkspaceButton>
          </nav>

          <div className="flex shrink-0 items-center">
            <WorkspaceButton
              active={activeTab === "history"}
              onClick={() => onTabChange("history")}
              data-testid="tab-history"
            >
              <History className="h-4 w-4" />
              Historia
            </WorkspaceButton>
            <WorkspaceButton
              active={activeTab === "chat"}
              onClick={() => onTabChange("chat")}
              data-testid="tab-chat"
              aria-label={unreadLabel}
            >
              <MessageCircle className="h-4 w-4" />
              Chat
              {chatUnreadCount > 0 ? (
                <Badge
                  variant="danger"
                  size="sm"
                  className="tabular-nums"
                  aria-hidden="true"
                >
                  {chatUnreadCount > 99 ? "99+" : chatUnreadCount}
                </Badge>
              ) : null}
            </WorkspaceButton>

            <CollapsibleTrigger asChild>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="shrink-0 text-muted-foreground"
                aria-expanded={contextOpen}
                aria-controls="job-operational-context"
                data-testid="toggle-job-header"
                title={contextOpen ? "Ukryj zespół i priorytet" : "Pokaż zespół i priorytet"}
              >
                <UserCheck className="h-4 w-4" />
                <span className="hidden sm:inline">Zespół i priorytet</span>
                {contextOpen ? (
                  <ChevronUp className="h-4 w-4" />
                ) : (
                  <ChevronDown className="h-4 w-4" />
                )}
              </Button>
            </CollapsibleTrigger>
          </div>
        </div>

        <CollapsibleContent id="job-operational-context">
          <div className="space-y-3 border-t border-border bg-muted/30 p-4">
            {contextContent}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
