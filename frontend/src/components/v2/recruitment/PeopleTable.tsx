"use client";

/**
 * Tabela osób rekrutacji — cienka warstwa nad `VirtualTable`.
 *
 * Jedna tabela, dwa rodzaje wierszy (`types.ts`): osoby W PROCESIE i PROPOZYCJE
 * z bazy. Kolumny różnią się dokładnie tam, gdzie różni się pytanie: o osobie
 * w procesie chcemy wiedzieć „co dalej", o propozycji — „skąd i dlaczego".
 *
 * Tabela niczego nie sortuje ani nie filtruje sama (robi to `person-rows.ts`)
 * i nie wykonuje ruchów etapu — zgłasza intencję (`onRequestStageChange`,
 * `onRequestNote`), a ruch idzie przez `usePipelineMove` u rodzica. Jedyny
 * własny zapis to „Usuń z rekrutacji" z menu wiersza.
 */

import { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal } from "lucide-react";

import { candidatesApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { encodeJobBackRef } from "@/lib/url-filters";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/Toast";
import { candidatePipelinesQueryKey } from "@/components/CandidatePipelinesWidget";
import { ContactStatusBadge } from "@/components/candidate-contact/ContactStatusBadge";
import {
  VirtualTable,
  type VirtualTableColumn,
  type VirtualTableGroup,
  type VirtualTableKey,
  type VirtualTableSort,
} from "@/components/ds/VirtualTable";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { PipelineGroupKey } from "@/lib/pipeline-flow";

import {
  defaultCollapsedFor,
  isOffTemplateRow,
  rowBadges,
  type PersonSort,
  type PersonSortKey,
  type RowBadgeTone,
} from "./person-rows";
import {
  PROPOSAL_SOURCE_LABEL,
  type PersonRow,
  type PersonRowGroup,
  type ProcessPersonRow,
  type ProposalPersonRow,
  type ProposalSource,
} from "./types";

export interface PeopleTableProps {
  /** Który zestaw kolumn — jawnie, bo pusta lista nie powie, czym jest. */
  variant: "process" | "proposal";
  rows: PersonRow[];
  jobId: number;
  groups?: PersonRowGroup[] | null;

  /** Bez `onSelectionChange` tabela nie ma checkboxów (tylko do odczytu). */
  selectedKeys?: Set<VirtualTableKey>;
  onSelectionChange?: (next: Set<VirtualTableKey>) => void;

  activeKey?: string | null;
  onActiveChange?: (row: PersonRow) => void;
  /** Enter na aktywnym wierszu. */
  onRowActivate?: (row: PersonRow) => void;

  sort?: PersonSort | null;
  /** `null` = wróć do sortowania domyślnego. */
  onSortChange?: (next: PersonSort | null) => void;

  readOnly?: boolean;
  /** Definicje etapów ze scorecardem — odznaka „Scorecard". */
  stagesWithScorecard?: ReadonlySet<number> | null;
  contactFeatureEnabled?: boolean;

  /** Skrót „E" — zmiana etapu aktywnej osoby. */
  onRequestStageChange?: (row: ProcessPersonRow) => void;
  /** Skrót „N" — notatka do aktywnej osoby. */
  onRequestNote?: (row: ProcessPersonRow) => void;
  /** Po udanym „Usuń z rekrutacji". */
  onRemoved?: (row: ProcessPersonRow) => void;

  loading?: boolean;
  empty?: React.ReactNode;
  footer?: React.ReactNode;
  /** `false` w testach (jsdom nie ma layoutu). */
  virtualize?: boolean;
  className?: string;
}

// ── Komórki ───────────────────────────────────────────────────────────

/** Pigułka etapu — kolor mówi o GRUPIE etapu, nazwa o etapie. */
const STAGE_PILL_CLASS: Record<PipelineGroupKey, string> = {
  posting: "bg-muted text-muted-foreground",
  intake: "bg-muted text-muted-foreground",
  screening: "bg-info-muted text-info-muted-foreground",
  verification: "bg-primary/10 text-primary",
  client: "bg-warning-muted text-warning-muted-foreground",
  contract: "bg-success-muted text-success-muted-foreground",
  closed: "bg-destructive-muted text-destructive-muted-foreground",
};

const SOURCE_PILL_CLASS: Record<ProposalSource, string> = {
  full_base: "bg-muted text-muted-foreground",
  new_cv: "bg-primary/10 text-primary",
  similar_projects: "bg-info-muted text-info-muted-foreground",
  recommendation: "bg-success-muted text-success-muted-foreground",
  marketplace: "bg-warning-muted text-warning-muted-foreground",
};

const BADGE_CLASS: Record<RowBadgeTone, string> = {
  warning: "bg-warning-muted text-warning-muted-foreground",
  danger: "bg-destructive-muted text-destructive-muted-foreground",
  info: "bg-info-muted text-info-muted-foreground",
};

const pillBase =
  "inline-flex h-[22px] items-center whitespace-nowrap rounded-md px-2 text-[11px] font-semibold";

function StagePill({ row }: { row: ProcessPersonRow }) {
  const offTemplate = isOffTemplateRow(row);
  return (
    <span
      className={cn(
        pillBase,
        offTemplate
          ? "bg-warning-muted text-warning-muted-foreground"
          : STAGE_PILL_CLASS[row.group],
      )}
      title={offTemplate ? "Etap spoza szablonu tej rekrutacji" : row.stageLabel}
    >
      <span className="max-w-[108px] truncate">{row.stageLabel}</span>
    </span>
  );
}

/**
 * „Następny krok": kolor niesie pilność i to, PO CZYJEJ stronie jest ruch —
 * wyszarzony wiersz znaczy „czekamy na kogoś", nie „nic się nie dzieje".
 */
function nextStepClass(row: ProcessPersonRow): string {
  const { tone, owner } = row.nextAction;
  if (tone === "due") return "text-destructive-muted-foreground font-medium";
  if (tone === "gate") return "text-warning-muted-foreground font-medium";
  return owner === "recruiter" ? "text-foreground" : "text-muted-foreground";
}

function NextStepCell({
  row,
  stagesWithScorecard,
  contactFeatureEnabled,
}: {
  row: ProcessPersonRow;
  stagesWithScorecard?: ReadonlySet<number> | null;
  contactFeatureEnabled: boolean;
}) {
  const badges = rowBadges(row, { stagesWithScorecard });
  const label = row.nextAction.label || "—";
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      <span className={cn("min-w-0 truncate", nextStepClass(row))} title={label}>
        {label}
      </span>
      {badges.map((badge) => (
        <span
          key={badge.key}
          title={badge.title}
          className={cn(
            "inline-flex h-[18px] shrink-0 items-center rounded px-1.5 text-[10px] font-semibold",
            BADGE_CLASS[badge.tone],
          )}
        >
          {badge.label}
        </span>
      ))}
      {contactFeatureEnabled && row.item.contact_case ? (
        <ContactStatusBadge
          contactCase={row.item.contact_case}
          showHistorical={false}
          className="shrink-0"
        />
      ) : null}
    </span>
  );
}

function daysLabel(days: number | null): string {
  if (days == null) return "—";
  if (days <= 0) return "dziś";
  return `${days} d`;
}

function fitClass(score: number): string {
  if (score >= 85) return "text-success-muted-foreground";
  if (score >= 75) return "text-primary";
  return "text-warning-muted-foreground";
}

/** `null` = „nie policzono". NIGDY zero zastępcze — zero to realny wynik. */
/**
 * Krótka etykieta nagłówka, która MIEŚCI się w wąskiej kolumnie przy 1440 px
 * („W ET…", „D…" były nieczytelne), z pełną nazwą w `title` i dla czytników.
 */
export function ShortHeader({ short, full }: { short: string; full: string }) {
  return (
    <span title={full}>
      <span aria-hidden="true">{short}</span>
      <span className="sr-only">{full}</span>
    </span>
  );
}

function FitCell({ score }: { score: number | null }) {
  if (score == null) {
    return (
      <span className="text-muted-foreground" title="Nie policzono" aria-label="Dopasowanie: nie policzono">
        —
      </span>
    );
  }
  return (
    <span
      className={cn("font-semibold tabular-nums", fitClass(score))}
      aria-label={`Dopasowanie: ${score} na 100`}
    >
      {score}
    </span>
  );
}

function dash(value: string | null): React.ReactNode {
  return value ?? <span className="text-muted-foreground">—</span>;
}

function ProposalNameCell({ row }: { row: ProposalPersonRow }) {
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      <span className="min-w-0 truncate font-semibold">{row.fullName}</span>
      {row.isNew ? (
        <span className="inline-flex h-[18px] shrink-0 items-center rounded bg-primary/10 px-1.5 text-[10px] font-semibold text-primary">
          nowa
        </span>
      ) : null}
      {row.previouslyDismissed ? (
        <span
          className="inline-flex h-[18px] shrink-0 items-center rounded bg-muted px-1.5 text-[10px] font-semibold text-muted-foreground"
          title="Ta osoba była wcześniej pominięta — wróciła, bo pojawiło się coś nowego"
        >
          wcześniej pominięta
        </span>
      ) : null}
    </span>
  );
}

// ── Sortowanie nagłówkami ─────────────────────────────────────────────

const SORT_KEYS: ReadonlySet<string> = new Set<PersonSortKey>(["action", "days", "fit", "name"]);

// ── Komponent ─────────────────────────────────────────────────────────

const getRowKey = (row: PersonRow): VirtualTableKey => row.key;
const getRowLabel = (row: PersonRow): string => row.fullName;
const KEY_COMMANDS = ["e", "n"];

export function PeopleTable({
  variant,
  rows,
  jobId,
  groups,
  selectedKeys,
  onSelectionChange,
  activeKey = null,
  onActiveChange,
  onRowActivate,
  sort = null,
  onSortChange,
  readOnly = false,
  stagesWithScorecard,
  contactFeatureEnabled = false,
  onRequestStageChange,
  onRequestNote,
  onRemoved,
  loading = false,
  empty,
  footer,
  virtualize = true,
  className,
}: PeopleTableProps) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [pendingRemoval, setPendingRemoval] = useState<ProcessPersonRow | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  // `null` = użytkownik nic nie klikał → domyślne zwinięcie liczone z grup
  // (nigdy nie chowa wszystkiego). Po pierwszym kliknięciu decyduje on.
  const [userCollapsed, setUserCollapsed] = useState<Set<string> | null>(null);
  const collapsed = useMemo(
    () => userCollapsed ?? defaultCollapsedFor(groups ?? []),
    [userCollapsed, groups],
  );

  const profileHref = useCallback(
    (candidateId: number) =>
      `/candidates/${candidateId}?${encodeJobBackRef(jobId).toString()}`,
    [jobId],
  );

  const confirmRemoval = useCallback(async () => {
    if (!pendingRemoval) return;
    const row = pendingRemoval;
    setRemoveBusy(true);
    try {
      await candidatesApi.removeFromRecruitment(row.candidateId, jobId);
      // OBA klucze tablicy (string i number) — patrz CLAUDE.md „Pipeline
      // rekrutacji": unieważnienie jednego zostawia drugi widok ze starą listą.
      queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
      queryClient.invalidateQueries({ queryKey: ["candidate-history"] });
      queryClient.invalidateQueries({
        queryKey: candidatePipelinesQueryKey(row.candidateId),
      });
      showSuccess(`${row.fullName} — usunięty z rekrutacji.`);
      setPendingRemoval(null);
      onRemoved?.(row);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się usunąć kandydata z rekrutacji."));
    } finally {
      setRemoveBusy(false);
    }
  }, [pendingRemoval, jobId, queryClient, showSuccess, showError, onRemoved]);

  const columns = useMemo<Array<VirtualTableColumn<PersonRow>>>(() => {
    // (nagłówki skrócone: patrz `ShortHeader`)
    const tail: Array<VirtualTableColumn<PersonRow>> = [
      { key: "rate", header: "Stawka", width: "92px", render: (row) => dash(row.rateLabel) },
      {
        key: "availability",
        header: "Dostępność",
        // 10 wersalików 11 px z `tracking-wide` nie mieściło się w 104 px.
        width: "116px",
        render: (row) => (
          <span className="text-muted-foreground" title={row.availabilityLabel ?? undefined}>
            {dash(row.availabilityLabel)}
          </span>
        ),
      },
      {
        key: "fit",
        header: <ShortHeader short="Dop." full="Dopasowanie" />,
        // Skrót + ikona sortowania: w 52 px zostawało „D…".
        width: "70px",
        sortKey: "fit",
        render: (row) => <FitCell score={row.fitScore} />,
      },
    ];

    if (variant === "proposal") {
      return [
        {
          key: "name",
          header: "Kandydat",
          width: "minmax(0,1.25fr)",
          sortKey: "name",
          render: (row) =>
            row.kind === "proposal" ? (
              <ProposalNameCell row={row} />
            ) : (
              <span className="font-semibold">{row.fullName}</span>
            ),
        },
        {
          key: "source",
          header: "Źródło",
          width: "minmax(124px,0.9fr)",
          render: (row) =>
            row.kind === "proposal" ? (
              <span className="flex min-w-0 items-center gap-1 overflow-hidden">
                {row.sources.map((source) => (
                  <span key={source} className={cn(pillBase, "shrink-0", SOURCE_PILL_CLASS[source])}>
                    {PROPOSAL_SOURCE_LABEL[source]}
                  </span>
                ))}
              </span>
            ) : null,
        },
        {
          key: "reason",
          header: "Dlaczego pasuje",
          width: "minmax(0,1.5fr)",
          render: (row) =>
            row.kind === "proposal" ? (
              <span title={row.reason ?? undefined}>{dash(row.reason)}</span>
            ) : null,
        },
        ...tail,
      ];
    }

    return [
      {
        key: "name",
        header: "Kandydat",
        width: "minmax(0,1.25fr)",
        sortKey: "name",
        render: (row) => (
          <span className="font-semibold" title={row.fullName}>
            {row.fullName}
          </span>
        ),
      },
      {
        key: "stage",
        header: "Etap",
        width: "132px",
        render: (row) => (row.kind === "process" ? <StagePill row={row} /> : null),
      },
      {
        key: "next",
        header: "Następny krok",
        width: "minmax(0,1.5fr)",
        sortKey: "action",
        render: (row) =>
          row.kind === "process" ? (
            <NextStepCell
              row={row}
              stagesWithScorecard={stagesWithScorecard}
              contactFeatureEnabled={contactFeatureEnabled}
            />
          ) : null,
      },
      {
        key: "days",
        header: <ShortHeader short="Dni" full="W etapie (dni)" />,
        width: "64px",
        sortKey: "days",
        render: (row) =>
          row.kind === "process" ? (
            <span className="tabular-nums text-muted-foreground">{daysLabel(row.daysInStage)}</span>
          ) : null,
      },
      ...tail,
      {
        key: "menu",
        header: <span className="sr-only">Akcje</span>,
        width: "36px",
        align: "center",
        render: (row) =>
          row.kind === "process" ? (
            // Klik w menu nie może aktywować wiersza (i przeładować panelu).
            <span onClick={(event) => event.stopPropagation()}>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    aria-label={`Akcje: ${row.fullName}`}
                    className="flex size-6 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <MoreHorizontal className="size-4" aria-hidden />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem asChild>
                    <Link href={profileHref(row.candidateId)}>Pełny profil</Link>
                  </DropdownMenuItem>
                  {!readOnly ? (
                    <DropdownMenuItem
                      className="text-destructive focus:text-destructive"
                      // Radix oddaje fokus PO `onSelect` — dialog otwarty w tym
                      // samym ticku zamknąłby się przy zwrocie fokusu.
                      onSelect={() => window.setTimeout(() => setPendingRemoval(row), 0)}
                    >
                      Usuń z rekrutacji
                    </DropdownMenuItem>
                  ) : null}
                </DropdownMenuContent>
              </DropdownMenu>
            </span>
          ) : null,
      },
    ];
  }, [variant, stagesWithScorecard, contactFeatureEnabled, profileHref, readOnly]);

  const tableGroups = useMemo<VirtualTableGroup[] | undefined>(() => {
    if (!groups || groups.length === 0) return undefined;
    return groups.map((group) => ({
      key: group.key,
      label: group.label,
      hint: group.hint,
      rowKeys: group.rowKeys,
      collapsed: collapsed.has(group.key),
    }));
  }, [groups, collapsed]);

  const handleToggleGroup = useCallback((key: VirtualTableKey) => {
    setUserCollapsed(() => {
      const next = new Set(collapsed);
      const id = String(key);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, [collapsed]);

  const handleSortChange = useCallback(
    (next: VirtualTableSort | null) => {
      if (!onSortChange) return;
      if (next == null || !SORT_KEYS.has(next.key)) onSortChange(null);
      else onSortChange({ key: next.key as PersonSortKey, dir: next.dir });
    },
    [onSortChange],
  );

  const handleKeyCommand = useCallback(
    (key: string, row: PersonRow) => {
      if (row.kind !== "process") return;
      // „E" zmienia etap — dla konta tylko do odczytu skrót milczy, tak samo
      // jak milczy brak przycisku. Notatka („N") ma własną bramkę w panelu.
      if (key === "e" && !readOnly) onRequestStageChange?.(row);
      if (key === "n") onRequestNote?.(row);
    },
    [readOnly, onRequestStageChange, onRequestNote],
  );

  const handleActiveChange = useCallback(
    (_key: VirtualTableKey, row: PersonRow) => onActiveChange?.(row),
    [onActiveChange],
  );

  return (
    <>
      <VirtualTable<PersonRow>
        aria-label={variant === "proposal" ? "Propozycje z bazy" : "Osoby w rekrutacji"}
        columns={columns}
        rows={rows}
        getRowKey={getRowKey}
        getRowLabel={getRowLabel}
        groups={tableGroups}
        onToggleGroup={handleToggleGroup}
        selectedKeys={readOnly ? undefined : selectedKeys}
        onSelectionChange={readOnly ? undefined : onSelectionChange}
        activeKey={activeKey}
        onActiveChange={handleActiveChange}
        onRowActivate={onRowActivate}
        keyCommands={variant === "process" ? KEY_COMMANDS : undefined}
        onKeyCommand={variant === "process" ? handleKeyCommand : undefined}
        sort={sort}
        onSortChange={onSortChange ? handleSortChange : undefined}
        loading={loading}
        empty={empty}
        footer={footer}
        virtualize={virtualize}
        className={className}
      />

      <Dialog
        open={pendingRemoval != null}
        onOpenChange={(open) => {
          if (!open && !removeBusy) setPendingRemoval(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Usunąć kandydata z tej rekrutacji?</DialogTitle>
            <DialogDescription>
              <span className="font-medium text-foreground">{pendingRemoval?.fullName}</span>{" "}
              zostanie zdjęty z pipeline&apos;u tej rekrutacji. Usunięta zostanie cała historia jego
              etapów wraz z powiązanymi snapshotami CV i linkami do udostępnień. Tej operacji nie
              można cofnąć — kandydata można jednak dodać do rekrutacji ponownie. Profil kandydata
              i jego umowy pozostają bez zmian.
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            <p className="text-sm text-muted-foreground">
              Jeśli chcesz zapisać powód rozstania, użyj „Odrzuć” — odrzucenie zostaje w historii
              i w statystykach, usunięcie nie.
            </p>
          </DialogBody>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setPendingRemoval(null)}
              disabled={removeBusy}
            >
              Anuluj
            </Button>
            <Button
              variant="destructive"
              onClick={() => void confirmRemoval()}
              loading={removeBusy}
              disabled={removeBusy}
            >
              Usuń z rekrutacji
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
