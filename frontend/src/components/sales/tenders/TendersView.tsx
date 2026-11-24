"use client";

import { ExternalLink, Play } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useRestoreTender,
  useRunTenders,
  useSalesTenders,
  type TenderNotice,
  type TenderRun,
  type Tenders,
} from "@/lib/api/sales-tenders";
import { resolveViewState } from "@/lib/view-state";

import { TenderRulesPanel } from "./TenderRulesPanel";
import { businessToday, deadlineLabel, formatMoment } from "./tender-dates";

type View = "created" | "rejected" | "rules";

const SOURCE = { bzp: "BZP", ted: "TED" } as const;

function RunLine({ data }: { data: Tenders }) {
  const run = useRunTenders();
  const { showError, showSuccess } = useToast();
  const last: TenderRun | null = data.last_run;
  const running = last?.status === "running";
  const counts = last?.counts ?? {};
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {!data.enabled && (
          <Badge variant="neutral" size="md">
            Bieg codzienny wyłączony
          </Badge>
        )}
        {last?.status === "ok" && last.started_at && (
          <span data-testid="tenders-last-run">
            Ostatni bieg {formatMoment(last.started_at)}: BZP{" "}
            <span className="tabular-nums text-foreground">{counts.bzp ?? 0}</span>, TED{" "}
            <span className="tabular-nums text-foreground">{counts.ted ?? 0}</span> · do bramki{" "}
            <span className="tabular-nums text-foreground">{counts.it ?? 0}</span> · założone{" "}
            <span className="tabular-nums text-foreground">{counts.created ?? 0}</span> · odsiane{" "}
            <span className="tabular-nums text-foreground">{counts.rejected ?? 0}</span> · zamknięte po terminie{" "}
            <span className="tabular-nums text-foreground">{counts.closed ?? 0}</span>
            {(counts.updated ?? 0) > 0 && (
              <>
                {" "}
                · zmiany ogłoszeń <span className="tabular-nums text-foreground">{counts.updated}</span>
              </>
            )}
          </span>
        )}
        {!last && <span>Bramka jeszcze nie biegła.</span>}
        {data.enabled && <span>Biegi w dni robocze od 5:30.</span>}
        {data.can_run && (
          <Button
            size="sm"
            variant="outline"
            className="ml-auto"
            disabled={running || run.isPending}
            onClick={() =>
              run.mutate(undefined, {
                onSuccess: () => showSuccess("Bieg ruszył. Lista odświeży się sama."),
                onError: (error) => showError(apiErrorMessage(error, "Nie udało się uruchomić biegu.")),
              })
            }
          >
            <Play className="size-3.5" aria-hidden />
            Uruchom teraz
          </Button>
        )}
      </div>
      {running && <Alert variant="info" spinning title="Bieg trwa: pobieram BZP i TED i przepuszczam przez bramkę." />}
      {last?.status === "failed" && (
        <Alert
          variant="error"
          title={`Bieg ${last.started_at ? formatMoment(last.started_at) : ""} się nie udał`}
          description={last.error ?? "Szczegóły są w logu serwera."}
        />
      )}
    </div>
  );
}

function NoticeCell({ notice }: { notice: TenderNotice }) {
  return (
    <div className="min-w-0 space-y-0.5">
      <p className="font-medium text-foreground">{notice.buyer_name}</p>
      <p className="text-foreground">{notice.title}</p>
      <p className="text-xs text-muted-foreground">
        {notice.url ? (
          <a href={notice.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
            {SOURCE[notice.source]} {notice.number}
            <ExternalLink className="size-3" aria-hidden />
          </a>
        ) : (
          <>
            {SOURCE[notice.source]} {notice.number}
          </>
        )}
        {notice.buyer_city && <> · {notice.buyer_city}</>}
      </p>
    </div>
  );
}

function DeadlineCell({ notice, today }: { notice: TenderNotice; today: string }) {
  const label = deadlineLabel(notice.deadline_date, notice.deadline_at, today);
  if (!label) return <span className="text-xs text-muted-foreground">brak w ogłoszeniu</span>;
  return (
    <div className="whitespace-nowrap">
      <p className={`font-medium tabular-nums ${label.urgent ? "text-destructive" : "text-foreground"}`}>{label.date}</p>
      <p className="text-xs text-muted-foreground">{label.hint}</p>
    </div>
  );
}

function CreatedTable({ items, today }: { items: TenderNotice[]; today: string }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-28">Termin ofert</TableHead>
          <TableHead>Zamawiający i przedmiot</TableHead>
          <TableHead className="w-52">Dlaczego przeszło</TableHead>
          <TableHead className="w-48">Szansa</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((notice) => (
          <TableRow key={notice.id}>
            <TableCell className="align-top">
              <DeadlineCell notice={notice} today={today} />
            </TableCell>
            <TableCell className="align-top">
              <NoticeCell notice={notice} />
            </TableCell>
            <TableCell className="align-top text-xs text-muted-foreground">
              {notice.match_detail}
              {notice.restored_by && <p>Przywrócone przez: {notice.restored_by}</p>}
            </TableCell>
            <TableCell className="align-top">
              {notice.opportunity_id ? (
                <Link href={`/sales/opportunities/${notice.opportunity_id}`} className="text-primary hover:underline">
                  {notice.opportunity_status === "lost" ? "Zamknięta" : notice.opportunity_stage ?? "Szansa"}
                </Link>
              ) : (
                <span className="text-xs text-muted-foreground">szansa usunięta</span>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function RejectedTable({ items, today, canEdit }: { items: TenderNotice[]; today: string; canEdit: boolean }) {
  const restore = useRestoreTender();
  const { showError, showSuccess } = useToast();
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Ogłoszenie</TableHead>
          <TableHead className="w-56">Odpadło, bo</TableHead>
          <TableHead className="w-28">Termin ofert</TableHead>
          {canEdit && <TableHead className="w-32" aria-label="Akcje" />}
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((notice) => {
          const deadline = deadlineLabel(notice.deadline_date, notice.deadline_at, today);
          return (
            <TableRow key={notice.id}>
              <TableCell className="align-top">
                <NoticeCell notice={notice} />
              </TableCell>
              <TableCell className="align-top">
                <Badge variant={notice.rule === "expired" ? "neutral" : "danger"}>{notice.rule_label}</Badge>
                {notice.rule_detail && <p className="mt-1 text-xs text-muted-foreground">„{notice.rule_detail}”</p>}
              </TableCell>
              <TableCell className="align-top">
                <DeadlineCell notice={notice} today={today} />
              </TableCell>
              {canEdit && (
                <TableCell className="align-top text-right">
                  {!deadline?.past && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={restore.isPending}
                      onClick={() =>
                        restore.mutate(notice.id, {
                          onSuccess: () => showSuccess("Założono szansę w lejku Przetargi. Jesteś jej opiekunem."),
                          onError: (error) => showError(apiErrorMessage(error, "Nie udało się przywrócić ogłoszenia.")),
                        })
                      }
                    >
                      Przywróć
                    </Button>
                  )}
                </TableCell>
              )}
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

function NoticeList({ status }: { status: "created" | "rejected" }) {
  const query = useSalesTenders(status);
  const state = resolveViewState({ isLoading: query.isLoading, error: query.error, isSuccess: query.isSuccess });
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => void query.refetch()} />;
  }
  if (!query.data) return <p className="py-6 text-sm text-muted-foreground">Wczytywanie przetargów…</p>;
  const data = query.data;
  const today = businessToday();
  return (
    <div className="space-y-3">
      <RunLine data={data} />
      {query.isSuccess && data.items.length === 0 ? (
        <p className="py-6 text-sm text-muted-foreground">
          {status === "created"
            ? "W ostatnich 14 dniach bramka nie założyła żadnej szansy."
            : "W ostatnich 14 dniach nic nie odpadło."}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-border bg-card">
          {status === "created" ? (
            <CreatedTable items={data.items} today={today} />
          ) : (
            <RejectedTable items={data.items} today={today} canEdit={data.can_edit} />
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Sprzedaż → Leady → Przetargi (decyzja Artura 24.11.2026, wariant B): NEXUS czyta BZP
 * i TED, bramka z regułami Kingi zakłada szanse w lejku Przetargi. Ekran pokazuje,
 * co bramka założyła i co odsiała (z regułą i „Przywróć”), oraz reguły do edycji.
 */
export function TendersView() {
  const [view, setView] = useState<View>("created");
  const counts = useSalesTenders("created").data;
  return (
    <div className="space-y-3">
      <p className="max-w-3xl text-sm text-muted-foreground">
        Ogłoszenia, które przeszły reguły, są już szansami w lejku Przetargi na etapie „Identyfikacja”, z terminem
        składania ofert jako datą zamknięcia. Szansa, której nikt nie ruszył przed terminem, zamyka się sama z powodem
        „Termin minął”.
      </p>
      <SegmentedRadio<View>
        label="Widok przetargów"
        size="sm"
        value={view}
        onChange={setView}
        options={[
          { value: "created", label: `Założone szanse${counts ? ` (${counts.created})` : ""}` },
          { value: "rejected", label: `Odsiane${counts ? ` (${counts.rejected})` : ""}` },
          { value: "rules", label: "Reguły" },
        ]}
      />
      {view === "rules" ? <TenderRulesPanel /> : <NoticeList key={view} status={view} />}
    </div>
  );
}
