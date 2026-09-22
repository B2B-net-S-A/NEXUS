"use client";

import type { ReactNode } from "react";
import {
  BookOpen,
  ChevronDown,
  ChevronUp,
  ClipboardList,
  Ellipsis,
  LayoutGrid,
  Link2,
  MessageCircle,
  PencilLine,
  Sparkles,
  Table2,
  Target,
  Trophy,
  UserCheck,
  UserPlus,
  Wand2,
} from "lucide-react";

import { EntityHeader } from "@/components/ds/EntityHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { JobHeaderKpi, JobHeaderKpiTone } from "@/lib/job-header-kpis";
import type { JobDetailView } from "@/lib/job-detail-routing";
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

/**
 * DAWNE identyfikatory zakładek rekrutacji (do wersji 3 — dwanaście kroków na
 * listwie). Widoków jest dziś trzy (`JobDetailView`), ale ten typ zostaje:
 * warsztaty (`ScreeningWorkbench`, `SourcingHub`) i KPI nagłówka nadal mówią
 * tym słownikiem, a strona tłumaczy go przez `resolveLegacyJobTab`.
 */
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
  /** Aktywny widok: „Tabela" (`people`), „Tablica" (`board`) albo pełne „Zlecenie i Champion". */
  activeView: JobDetailView;
  onViewChange: (view: JobDetailView) => void;
  /**
   * Okno „Zlecenie" (fakty, zespół, priorytet, portale, zamknięcie) — tak samo
   * na każdym widoku, także na „Zlecenie i Champion": portale, zespół
   * i „Zamknij rekrutację" mieszkają wyłącznie w tym oknie.
   */
  onOpenOrder: () => void;
  /**
   * Ile rzeczy brakuje w zleceniu wg bramki gotowości. `undefined`/`null` =
   * nie wiadomo (rola spoza bramki, zapytanie w toku) — odznaki nie ma;
   * zero też jej nie pokazuje („brakuje 0" to szum).
   */
  orderMissingCount?: number | null;
  onOpenHistoryChat: () => void;
  onOpenQuestions: () => void;
  /** Okno „Podobne rekrutacje" (0341) — przepięcia osób wysłanych do klienta. */
  onOpenSimilar?: () => void;
  /** Połączone rekrutacje; `null`/`undefined` = nie wiadomo (bez odznaki). */
  similarLinkedCount?: number | null;
  /** Sugerowane podobne (niepołączone) — odznaka „≈ N". */
  similarSuggestedCount?: number | null;
  /**
   * „Mamy championa" (0341) — przełącznik Delivery Leada. `undefined` = rola
   * bez prawa (brak przycisku); status widać wtedy w odznace statusu.
   */
  championFound?: boolean;
  onToggleChampion?: () => void;
  championPending?: boolean;
  onAddCandidate?: () => void;
  onEdit?: () => void;
  onWriteAnnouncement?: () => void;
  onGenerateInviteLink?: () => void;
  /**
   * Narzędzia AI administratora (kryteria, scoring, embedding). Strona podaje
   * je WYŁĄCZNIE adminowi — do 09.2026 były dostępne tylko przy zaznaczonej
   * propozycji, więc rekrutacja bez propozycji nie miała do nich wejścia.
   */
  onOpenAiTools?: () => void;
  chatUnreadCount?: number;
  /** Osoby w procesie — licznik przy przełączniku widoków. `undefined` = nie policzono. */
  pipelineCount?: number;
  /**
   * Panel „Zespół i priorytet". W widokach „Tabela"/„Tablica" żyje w oknie
   * „Zlecenie", więc strona go tu nie podaje — wtedy nie ma ani przycisku,
   * ani panelu. Zostaje na pełnym widoku „Zlecenie i Champion".
   */
  contextOpen?: boolean;
  onContextOpenChange?: (open: boolean) => void;
  contextContent?: ReactNode;
}

function deferMenuAction(action: () => void) {
  window.setTimeout(action, 0);
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

/** Jedna pozycja przełącznika „Tabela | Tablica". */
function ViewSwitchButton({
  active,
  children,
  ...props
}: React.ComponentProps<"button"> & { active: boolean }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "bg-card text-foreground shadow-sm"
          : "text-muted-foreground hover:text-foreground",
      )}
      {...props}
    >
      {children}
    </button>
  );
}

/**
 * Nagłówek rekrutacji (wersja 3: „rekrutacja = jedna tabela").
 *
 * Pierwszy wiersz bez zmian: tożsamość, odznaki, obecni, „Dodaj kandydata"
 * i menu „…". Drugi wiersz zastąpił dwunastopozycyjną listwę kroków:
 * przełącznik widoku „Tabela | Tablica" oraz trzy przyciski otwierające okna
 * OBOK tabeli — „Zlecenie" (z odznaką „brakuje N"), „Historia i czat"
 * (z licznikiem nieprzeczytanych) i „Baza pytań". Kroki procesu są teraz
 * paskiem etapów nad tabelą, a nie nawigacją strony.
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
  activeView,
  onViewChange,
  onOpenOrder,
  orderMissingCount,
  onOpenHistoryChat,
  onOpenQuestions,
  onOpenSimilar,
  similarLinkedCount,
  similarSuggestedCount,
  championFound,
  onToggleChampion,
  championPending,
  onAddCandidate,
  onEdit,
  onWriteAnnouncement,
  onGenerateInviteLink,
  onOpenAiTools,
  chatUnreadCount = 0,
  pipelineCount,
  contextOpen = false,
  onContextOpenChange,
  contextContent,
}: JobDetailCompactHeaderProps) {
  const hasContext = contextContent != null;
  const unreadLabel =
    chatUnreadCount > 0
      ? `Historia i czat, ${chatUnreadCount > 99 ? "ponad 99" : chatUnreadCount} nieprzeczytane`
      : "Historia i czat";
  const missing =
    typeof orderMissingCount === "number" && orderMissingCount > 0
      ? orderMissingCount
      : null;

  return (
    <Collapsible open={hasContext && contextOpen} onOpenChange={onContextOpenChange}>
      <div className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="px-4 py-2.5">
          <EntityHeader
            density="compact"
            avatar={
              <span
                aria-hidden="true"
                className="mt-0.5 inline-flex h-7 w-7 items-center justify-center rounded-lg bg-primary/10 text-primary"
              >
                <Target className="h-4 w-4" />
              </span>
            }
            title={
              clientName ? (
                // Tytuł i klient w JEDNEJ linii: pełna nazwa prawna klienta
                // („Powszechna Kasa Oszczędności Bank Polski S.A") łamała
                // nagłówek na dwa wiersze. Tytuł zostaje w całości, klient się
                // ucina (pełna nazwa w `title`).
                <span className="flex min-w-0 items-baseline gap-x-2">
                  <span className="shrink-0">{title}</span>
                  {/* Separator i nazwa klienta w JEDNYM węźle tekstowym —
                      `{" · "}{clientName}` rozpadało się na trzy węzły, przez
                      co spacja przy kropce ginęła przy pierwszej zmianie
                      formatowania. */}
                  <span
                    className="min-w-0 truncate text-lg font-normal text-muted-foreground"
                    title={clientName}
                  >
                    {` · ${clientName}`}
                  </span>
                </span>
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

                {/* Menu „⋯" jest zawsze — niesie też „Bazę pytań" (makieta:
                    rzadziej używana, więc zeszła z paska nagłówka). */}
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
                      <DropdownMenuItem
                        onSelect={() => deferMenuAction(onOpenQuestions)}
                        data-testid="open-questions"
                      >
                        <BookOpen className="h-4 w-4" />
                        Baza pytań
                      </DropdownMenuItem>
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
                          Szkic ogłoszenia
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
                      {onOpenAiTools ? (
                        <>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            onSelect={() => deferMenuAction(onOpenAiTools)}
                            data-testid="open-ai-tools"
                          >
                            <Sparkles className="h-4 w-4" />
                            Narzędzia AI (administrator)
                          </DropdownMenuItem>
                        </>
                      ) : null}
                    </DropdownMenuContent>
                  </DropdownMenu>
              </>
            }
          />
        </div>

        {/* `flex-wrap` zamiast `overflow-x-auto`: przy ciasnym oknie pasek ma
            się ZŁAMAĆ, a nie schować końcówkę za niewidoczny pasek przewijania.
            Przycisk, którego nie widać, nie istnieje dla użytkownika. */}
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-border px-3 py-1.5">
          <div
            role="group"
            aria-label="Widok rekrutacji"
            className="inline-flex items-center gap-0.5 rounded-lg bg-muted p-0.5"
          >
            <ViewSwitchButton
              active={activeView === "people"}
              onClick={() => onViewChange("people")}
              data-testid="view-people"
            >
              <Table2 className="h-3.5 w-3.5" aria-hidden="true" />
              Tabela
              {typeof pipelineCount === "number" ? (
                <CountBadge value={pipelineCount} />
              ) : null}
            </ViewSwitchButton>
            <ViewSwitchButton
              active={activeView === "board"}
              onClick={() => onViewChange("board")}
              data-testid="view-board"
            >
              <LayoutGrid className="h-3.5 w-3.5" aria-hidden="true" />
              Tablica
            </ViewSwitchButton>
          </div>

          <nav
            className="flex min-w-0 flex-wrap items-center gap-1.5"
            aria-label="Sekcje rekrutacji"
          >
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={onOpenOrder}
              data-testid="open-order"
            >
              <ClipboardList className="h-4 w-4" aria-hidden="true" />
              Zlecenie
              {missing != null ? (
                <Badge variant="warning" size="sm" className="tabular-nums">
                  brakuje {missing}
                </Badge>
              ) : null}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={onOpenHistoryChat}
              aria-label={unreadLabel}
              data-testid="open-history-chat"
            >
              <MessageCircle className="h-4 w-4" aria-hidden="true" />
              Historia i czat
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
            </Button>

            {onOpenSimilar ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={onOpenSimilar}
                data-testid="open-similar"
                title="Połącz podobne rekrutacje — osoby wysłane tam do klienta trafią do „Do przejrzenia”"
              >
                <Link2 className="h-4 w-4" aria-hidden="true" />
                Podobne rekrutacje
                {similarLinkedCount ? (
                  <Badge size="sm" variant="info" className="tabular-nums">
                    ↻ {similarLinkedCount}
                  </Badge>
                ) : similarSuggestedCount ? (
                  <Badge size="sm" variant="outline" className="tabular-nums">
                    ≈ {similarSuggestedCount}
                  </Badge>
                ) : null}
              </Button>
            ) : null}
            {onToggleChampion ? (
              <Button
                type="button"
                size="sm"
                variant={championFound ? "primary" : "outline"}
                onClick={onToggleChampion}
                disabled={championPending}
                aria-pressed={Boolean(championFound)}
                data-testid="toggle-champion"
                title={
                  championFound
                    ? "Cofnij „Mamy championa” — rekrutacja wraca do „Szukamy”"
                    : "Mamy championa — dalej nie szukamy"
                }
              >
                <Trophy className="h-4 w-4" aria-hidden="true" />
                {championFound ? "Mamy championa" : "Oznacz: mamy championa"}
              </Button>
            ) : null}
          </nav>

          {hasContext ? (
            <CollapsibleTrigger asChild>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="ml-auto shrink-0 text-muted-foreground"
                aria-expanded={contextOpen}
                aria-controls="job-operational-context"
                data-testid="toggle-job-header"
                title={contextOpen ? "Ukryj zespół i priorytet" : "Pokaż zespół i priorytet"}
              >
                <UserCheck className="h-4 w-4" />
                <span className="hidden xl:inline">Zespół i priorytet</span>
                {contextOpen ? (
                  <ChevronUp className="h-4 w-4" />
                ) : (
                  <ChevronDown className="h-4 w-4" />
                )}
              </Button>
            </CollapsibleTrigger>
          ) : null}
        </div>

        {hasContext ? (
          <CollapsibleContent id="job-operational-context">
            <div className="space-y-3 border-t border-border bg-muted/30 p-4">
              {contextContent}
            </div>
          </CollapsibleContent>
        ) : null}
      </div>
    </Collapsible>
  );
}
