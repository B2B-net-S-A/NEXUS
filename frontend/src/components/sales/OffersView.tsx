"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FileSignature } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/ds/EmptyState";
import { FilterBar } from "@/components/ds/FilterBar";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TruncatedText } from "@/components/ds/TruncatedText";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useCompleteActivity,
  useOffers,
  usePipelines,
  useTakeOverOpportunity,
  type OfferRow,
  type OfferScope,
  type OfferSectionTotals,
} from "@/lib/api/sales";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatDayMonthPl, formatIsoDatePl } from "@/lib/date-pl";
import { hasPermission } from "@/lib/permissions";
import { useUrlWriter } from "@/lib/url-selection";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

import { NextStepDialog } from "./CallLogDialogs";
import { daysLabel, formatDealNumber } from "./format";
import { plural } from "./my-day";
import { CloseOfferDialog, PostponeOfferDialog } from "./OfferDecisionDialogs";
import { OFFER_SCOPES, lostStages, offerStepText, scopeLabel, sectionHint, stageNote } from "./offers";
import { shortCompany } from "./step";

/** Tyle pozycji „Do decyzji” widać od razu; reszta pod „Pokaż pozostałe”. */
const DECIDE_PAGE = 25;
const COLUMNS = 6;
const ROW_BUTTON = "h-7 px-2.5";

interface SectionRowProps {
  title: string;
  totals: OfferSectionTotals;
}

function SectionRow({ title, totals }: SectionRowProps) {
  return (
    <TableRow className="hover:bg-transparent">
      <TableCell colSpan={COLUMNS} className="border-y border-border bg-muted/40 px-3 py-1">
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</span>
          <span className="text-xs text-muted-foreground">{sectionHint(totals)}</span>
        </div>
      </TableCell>
    </TableRow>
  );
}

function NoteRow({ children }: { children: React.ReactNode }) {
  return (
    <TableRow className="hover:bg-transparent">
      <TableCell colSpan={COLUMNS} className="text-sm text-muted-foreground">
        {children}
      </TableCell>
    </TableRow>
  );
}

/**
 * Sprzedaż → Oferty: co robisz dalej przy wysłanych ofertach („W toku”) i które pozycje
 * trzeba rozstrzygnąć („Do decyzji”). NEXUS nie ma generatora ofert (decyzja 26.10.2026),
 * więc oferta to etap szansy. Sekcje, dni bez ruchu i liczniki liczy backend.
 */
export function OffersView() {
  const searchParams = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const [q, setQ] = useState(searchParams?.get("q") ?? "");
  // Przy wejściu serwer sam daje „Moje” osobie, która prowadzi jakąś ofertę.
  const [chosenScope, setChosenScope] = useState<OfferScope | undefined>(undefined);
  const [showAll, setShowAll] = useState(false);
  const [postponing, setPostponing] = useState<OfferRow | null>(null);
  const [closing, setClosing] = useState<OfferRow | null>(null);
  const [planning, setPlanning] = useState<OfferRow | null>(null);
  const offers = useOffers({ scope: chosenScope, q });
  const pipelines = usePipelines();
  const complete = useCompleteActivity();
  const takeOver = useTakeOverOpportunity();
  const { showError, showSuccess } = useToast();
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");

  const data = offers.data;
  // Zakres z pierwszej odpowiedzi zostaje na całą wizytę. Bez tego każde odświeżenie
  // wybierałoby go od nowa: po pierwszym „Przejmij” osoba bez własnych ofert lądowałaby
  // w „Moje” z jedną pozycją i traciła z oczu resztę „Do decyzji”.
  if (chosenScope === undefined && data?.scope !== undefined) setChosenScope(data.scope);
  const scope = chosenScope ?? data?.scope;
  const items = data?.items ?? [];
  const inProgress = items.filter((item) => item.section === "in_progress");
  const toDecide = items.filter((item) => item.section === "to_decide");
  const shownToDecide = showAll ? toDecide : toDecide.slice(0, DECIDE_PAGE);
  const totals = data && scope ? data.totals[scope] : undefined;
  const overdueClose = items.filter((item) => item.close_overdue).length;
  const defaultPipelineId = pipelines.data?.find((pipeline) => pipeline.is_default)?.id ?? null;
  const state = resolveViewState({
    isLoading: offers.isLoading,
    error: offers.error,
    isSuccess: offers.isSuccess,
    isEmpty: items.length === 0,
  });

  const onDone = (row: OfferRow) => {
    if (!row.step?.activity_id) return;
    complete.mutate(
      { id: row.step.activity_id },
      { onError: (error) => showError(apiErrorMessage(error, "Nie udało się odhaczyć kroku.")) },
    );
  };

  const onTakeOver = (row: OfferRow) => {
    takeOver.mutate(row.id, {
      onSuccess: () =>
        showSuccess(
          row.is_offer
            ? "Przejęto. Oferta jest teraz u Ciebie."
            : `Przejęto. Szansa jest u Ciebie na etapie „${row.stage.name}” i znika z tej listy.`,
        ),
      onError: (error) => showError(apiErrorMessage(error, "Nie udało się przejąć szansy.")),
    });
  };

  const renderRow = (row: OfferRow) => {
    const note = stageNote(row, defaultPipelineId);
    return (
      <TableRow key={row.id} className={CALM_ROW}>
        <TableCell>
          <Link href={`/sales/opportunities/${row.id}`} className="font-medium text-foreground hover:underline">
            {/* Krótka nazwa, bo pełna rejestrowa zjada kolumnę; pełna zostaje w dymku. */}
            <TruncatedText className="max-w-full" title={row.company.name}>
              {shortCompany(row.company.name)}
            </TruncatedText>
          </Link>
          <TruncatedText className={cn(CALM_SUBLINE, "max-w-full")}>
            {/* Etap pierwszy: przy szansie spoza ofert to on mówi, co to za pozycja, a koniec się ucina. */}
            {note ? `${note} · ${row.title}` : row.title}
          </TruncatedText>
        </TableCell>
        <TableCell className="text-sm text-muted-foreground">
          <TruncatedText className="max-w-full">{row.owner?.name ?? "bez opiekuna"}</TruncatedText>
          {row.owner && !row.owner_in_sales && (
            <Badge variant="warning" size="sm" className="mt-0.5">
              poza Sprzedażą
            </Badge>
          )}
        </TableCell>
        <TableCell className={CALM_AMOUNT}>{formatDealNumber(row.mrr_value)}</TableCell>
        <TableCell className="whitespace-nowrap text-right text-sm tabular-nums text-foreground">
          {daysLabel(row.idle_days)}
        </TableCell>
        <TableCell
          className={cn(
            "whitespace-nowrap text-right text-sm tabular-nums",
            row.close_overdue ? "text-destructive" : "text-muted-foreground",
          )}
        >
          {formatIsoDatePl(row.expected_close_date)}
        </TableCell>
        <TableCell className="whitespace-nowrap text-right">
          {row.section === "to_decide" ? (
            canEdit ? (
              <span className="inline-flex gap-1.5">
                {row.owner_in_sales ? (
                  <Button size="sm" variant="outline" className={ROW_BUTTON} onClick={() => setPostponing(row)}>
                    Odłóż do…
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    className={ROW_BUTTON}
                    loading={takeOver.isPending && takeOver.variables === row.id}
                    onClick={() => onTakeOver(row)}
                  >
                    Przejmij
                  </Button>
                )}
                <Button size="sm" variant="outline" className={ROW_BUTTON} onClick={() => setClosing(row)}>
                  Zamknij z powodem
                </Button>
              </span>
            ) : (
              <span className="text-xs text-muted-foreground">
                {row.reason === "owner_left" ? "bez opiekuna w Sprzedaży" : "ponad 30 dni bez ruchu"}
              </span>
            )
          ) : (
            <span className="flex items-center justify-end gap-2">
              <span className="min-w-0 text-xs text-muted-foreground">
                {row.step ? (
                  <TruncatedText
                    className={cn("max-w-full", row.step.overdue && "text-warning-muted-foreground")}
                  >
                    {`${row.step.overdue ? "Po terminie: " : ""}${offerStepText(row.step)}`}
                  </TruncatedText>
                ) : (
                  !row.postponed && "brak kroku"
                )}
                {row.postponed && <span className="block">odłożone do {formatDayMonthPl(row.keep_open_until)}</span>}
              </span>
              {canEdit && row.step?.activity_id != null && (
                <Button
                  size="sm"
                  className={ROW_BUTTON}
                  loading={complete.isPending && complete.variables?.id === row.step.activity_id}
                  onClick={() => onDone(row)}
                >
                  Zrobione
                </Button>
              )}
              {canEdit && !row.step && (
                <Button size="sm" variant="outline" className={ROW_BUTTON} onClick={() => setPlanning(row)}>
                  Zaplanuj
                </Button>
              )}
            </span>
          )}
        </TableCell>
      </TableRow>
    );
  };

  return (
    <div className="space-y-3">
      <FilterBar
        search={{
          value: q,
          onChange: (value) => {
            setQ(value);
            const trimmed = value.trim();
            replaceUrl(trimmed ? `${window.location.pathname}?q=${encodeURIComponent(trimmed)}` : window.location.pathname);
          },
          placeholder: "Szukaj oferty albo firmy…",
          ariaLabel: "Szukaj oferty",
        }}
        actions={
          <SegmentedRadio
            size="sm"
            label="Czyje pozycje"
            options={OFFER_SCOPES.map((value) => ({ value, label: scopeLabel(value, data?.totals) }))}
            value={scope}
            onChange={(value) => {
              setChosenScope(value);
              setShowAll(false);
            }}
          />
        }
      />
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie ofert…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void offers.refetch()} />
      ) : state === "empty" || !totals ? (
        <EmptyState
          icon={FileSignature}
          title="Nie ma tu żadnej pozycji"
          description="Oferta pojawia się tu, gdy szansa wejdzie na etap „Oferta wysłana”. Sprawdź też inny zakres albo wyszukiwanie."
        />
      ) : (
        <>
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground">
              {`W toku: ${totals.in_progress.count} · Do decyzji: ${totals.to_decide.count}`}
            </span>
            {overdueClose > 0 && (
              <>
                {" · "}
                <span className="text-destructive">
                  {`termin minął w ${plural(overdueClose, "pozycji", "pozycjach", "pozycjach")}`}
                </span>
              </>
            )}
          </p>
          <div className="relative overflow-x-auto">
            {/* Stałe szerokości: przy 1280 px tabela mieści się bez przewijania w bok, a nazwy się skracają. */}
            <Table density="compact" className="min-w-[940px] table-fixed">
              <colgroup>
                <col />
                <col className="w-40" />
                <col className="w-20" />
                <col className="w-20" />
                <col className="w-24" />
                <col className="w-[19.5rem]" />
              </colgroup>
              <TableHeader>
                <TableRow>
                  <TableHead className={CALM_HEAD}>Szansa</TableHead>
                  <TableHead className={CALM_HEAD}>Opiekun</TableHead>
                  <TableHead className={`${CALM_HEAD} whitespace-nowrap text-right`}>MRR (zł)</TableHead>
                  <TableHead className={`${CALM_HEAD} whitespace-nowrap text-right`}>Bez ruchu</TableHead>
                  <TableHead className={`${CALM_HEAD} text-right`}>Termin</TableHead>
                  <TableHead className={`${CALM_HEAD} whitespace-nowrap text-right`}>Co dalej</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <SectionRow title="W toku" totals={totals.in_progress} />
                {inProgress.length === 0 ? <NoteRow>Nic w toku w tym zakresie.</NoteRow> : inProgress.map(renderRow)}
                <SectionRow
                  title="Do decyzji · ponad 30 dni bez ruchu albo bez opiekuna w Sprzedaży"
                  totals={totals.to_decide}
                />
                {toDecide.length === 0 ? <NoteRow>Nic nie czeka na decyzję.</NoteRow> : shownToDecide.map(renderRow)}
              </TableBody>
            </Table>
          </div>
          {shownToDecide.length < toDecide.length && (
            <Button size="sm" variant="outline" onClick={() => setShowAll(true)}>
              {`Pokaż pozostałe (${toDecide.length - shownToDecide.length})`}
            </Button>
          )}
        </>
      )}
      {postponing && <PostponeOfferDialog offer={postponing} onClose={() => setPostponing(null)} />}
      {closing && (
        <CloseOfferDialog
          offer={closing}
          stages={lostStages(pipelines.data, closing.pipeline_id)}
          onClose={() => setClosing(null)}
        />
      )}
      {planning && (
        <NextStepDialog opportunityId={planning.id} outcome={null} personName={null} onClose={() => setPlanning(null)} />
      )}
    </div>
  );
}
