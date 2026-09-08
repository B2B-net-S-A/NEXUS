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
import type { JobHeaderKpi, JobHeaderKpiTone } from "@/lib/job-header-kpis";
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
  /**
   * Klient dopisany do tytułu (makieta: „Programista Python (ZOB-2947) ·
   * PKO Bank Polski"). Do 09.2026 nagłówka rekrutacji nie było w nim W OGÓLE,
   * więc na każdej zakładce poza listą trzeba było pamiętać, czyja to
   * rekrutacja — a to pierwsza rzecz, którą sprawdza się przed rozmową.
   */
  clientName?: string | null;
  referenceNumber?: string | null;
  badges?: ReactNode;
  /** Jedna linia faktów pod tytułem (patrz `lib/job-header-subtitle.ts`). */
  subtitle?: ReactNode;
  metadata?: ReactNode;
  /** Trzy liczby właściwe dla aktywnego kroku (`lib/job-header-kpis.ts`). */
  kpis?: JobHeaderKpi[];
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
        // `px-2` + `text-[13px]`, nie `px-3`/`text-sm`: przy 1440 px jedenaście
        // kroków ze starym paddingiem nie mieściło się w pasku, a `nav` miał
        // `overflow-x-auto`, więc ostatnia etykieta („Baza pytań") była UCIĘTA
        // do samej ikony. Ucięta etykieta czyta się jak brak funkcji, nie jak
        // brak miejsca — a przewijanego paska w poziomie nikt tam nie szukał.
        "h-10 gap-1.5 rounded-none border-b-2 px-2 text-[13px] whitespace-nowrap",
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

const KPI_TONE_CLASS: Record<JobHeaderKpiTone, string> = {
  neutral: "text-foreground",
  ok: "text-success",
  warn: "text-warning",
  bad: "text-destructive",
};

/**
 * Klaster trzech liczb po prawej stronie jobbara.
 *
 * `value === null` renderuje „—", nigdy zera: kanban i ranking ładują się
 * osobno, a zero jest zdaniem o rekrutacji, którego w tym momencie nikt
 * jeszcze nie sprawdził.
 */
function JobHeaderKpiCluster({ kpis }: { kpis: JobHeaderKpi[] }) {
  return (
    <div
      className="flex items-center gap-4 pr-1"
      data-testid="job-header-kpis"
      aria-label="Wskaźniki tego kroku"
    >
      {kpis.map((kpi) => (
        <div key={kpi.key} className="text-right leading-tight">
          <div
            className={cn(
              "text-sm font-bold tabular-nums",
              KPI_TONE_CLASS[kpi.tone],
            )}
          >
            {kpi.value ?? "—"}
          </div>
          <div className="text-[9.5px] uppercase tracking-eyebrow text-muted-foreground">
            {kpi.label}
          </div>
        </div>
      ))}
    </div>
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
  clientName,
  referenceNumber,
  badges,
  subtitle,
  metadata,
  kpis,
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
        <div className="px-4 py-2.5">
          <EntityHeader
            density="compact"
            title={
              clientName ? (
                <>
                  {title}
                  {/* Separator i nazwa klienta w JEDNYM węźle tekstowym —
                      `{" · "}{clientName}` rozpadało się na trzy węzły, przez
                      co spacja przy kropce ginęła przy pierwszej zmianie
                      formatowania. */}
                  <span className="font-normal text-muted-foreground">
                    {` · ${clientName}`}
                  </span>
                </>
              ) : (
                title
              )
            }
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
            subtitle={subtitle}
            metadata={metadata}
            actions={
              <>
                {kpis && kpis.length > 0 ? (
                  <JobHeaderKpiCluster kpis={kpis} />
                ) : null}
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

        {/* Listwa kroków — kolejność procesu, Historia i Chat po prawej.

            `flex-wrap` zamiast `overflow-x-auto`: przy ciasnym oknie listwa ma
            się ZŁAMAĆ na dwa wiersze, a nie schować końcówkę za niewidoczny
            pasek przewijania. Krok, którego nie widać, nie istnieje dla
            użytkownika — a to jedyna nawigacja tego ekranu. */}
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-2 border-t border-border px-1">
          <nav
            className="flex min-w-0 flex-wrap items-center"
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

            {/* Baza pytań to materiał pomocniczy, nie krok procesu — stoi za
                ostatnim krokiem (08 Umowa), jak w makietach programu. */}
            <WorkspaceButton
              active={activeTab === "questions"}
              onClick={() => onTabChange("questions")}
              data-testid="tab-questions"
            >
              <BookOpen className="h-4 w-4" />
              Baza pytań
            </WorkspaceButton>
          </nav>

          <div className="ml-auto flex shrink-0 items-center">
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
