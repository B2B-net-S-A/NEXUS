"use client";

import { PhoneCall, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { usePipelines } from "@/lib/api/sales";
import { useCallQueue, type CallQueue, type QueueItem, type QueueSection } from "@/lib/api/sales-calling";
import { hasPermission } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

import { formatWeekdayDayPl } from "@/lib/date-pl";

import { dayHeading } from "../my-day";
import { CallCard, type MeetingStage } from "./CallCard";
import { CallTableView } from "./CallTableView";
import { ExcelTransferDialog } from "./ExcelTransferDialog";
import { CampaignsDialog } from "./CampaignsDialog";
import { ImportListDialog } from "./ImportListDialog";
import {
  dayLine,
  isQueueEmpty,
  itemReason,
  nextKey,
  queueItems,
  queueLine,
  resolveSelection,
  SECTION_ORDER,
  SECTION_TITLES,
} from "./calling";

const SALES_PIPELINE_KEY = "sales";
const MEETING_STAGE_KEY = "qualifying-meeting";

function sectionHint(queue: CallQueue, section: QueueSection): string | null {
  const shown = queue[section].length;
  const total = queue.counts[section];
  return total > shown ? `${shown} z ${total}` : null;
}

interface RowProps {
  item: QueueItem;
  today: string;
  active: boolean;
  onSelect: () => void;
}

function QueueRow({ item, today, active, onSelect }: RowProps) {
  const ref = useRef<HTMLButtonElement>(null);
  // Po zapisie lista przechodzi do następnej pozycji: ma ją też pokazać, gdy leży poza ekranem.
  useEffect(() => {
    if (active) ref.current?.scrollIntoView?.({ block: "nearest" });
  }, [active]);
  return (
    <li>
      <button
        ref={ref}
        type="button"
        aria-current={active ? "true" : undefined}
        className={cn(
          "flex min-h-11 w-full items-center gap-2 px-3 py-1 text-left hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
          active && "bg-primary/5",
        )}
        onClick={onSelect}
      >
        <span className="min-w-0 flex-1 leading-tight">
          <span className="block truncate text-sm font-medium text-foreground">{item.company.name}</span>
          <span className="block truncate text-xs text-muted-foreground">{itemReason(item, today)}</span>
        </span>
        <span className="hidden w-44 shrink-0 truncate text-right text-xs text-muted-foreground sm:block">
          {item.person_title ?? item.person_name ?? ""}
        </span>
        <span
          className={cn(
            "w-24 shrink-0 whitespace-nowrap rounded-md border px-2 py-1 text-center text-xs font-medium",
            active ? "border-primary bg-primary text-primary-foreground" : "border-border text-foreground",
          )}
        >
          {active ? "W rozmowie" : "Zadzwoń"}
        </span>
      </button>
    </li>
  );
}

function CampaignFilter({
  queue,
  value,
  onChange,
}: {
  queue: CallQueue;
  value: number | null;
  onChange: (value: number | null) => void;
}) {
  if (queue.campaigns.length < 2 && value === null) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Kampania">
      {queue.campaigns.map((campaign) => (
        <Button
          key={campaign.id}
          size="sm"
          variant={value === campaign.id ? "primary" : "outline"}
          className="h-7 px-2"
          aria-pressed={value === campaign.id}
          onClick={() => onChange(value === campaign.id ? null : campaign.id)}
        >
          {campaign.name}
        </Button>
      ))}
    </div>
  );
}

interface QueueBoardProps {
  queue: CallQueue;
  canEdit: boolean;
  meetingStage: MeetingStage | null;
}

/** Lista i karta. Wybór pozycji jest przypięty: odświeżenie kolejki go nie podmienia. */
function QueueBoard({ queue, canEdit, meetingStage }: QueueBoardProps) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const previousOrder = useRef<string[]>([]);
  const items = queueItems(queue);
  const selected = resolveSelection(items, selectedKey, previousOrder.current);
  const selectedIndex = selected ? items.indexOf(selected) : -1;
  const upcomingKey = selected ? nextKey(items, selected.key) : null;
  const upcoming = items.find((item) => item.key === upcomingKey) ?? null;
  const resolvedKey = selected?.key ?? null;
  const order = items.map((item) => item.key).join("|");

  useEffect(() => {
    previousOrder.current = order ? order.split("|") : [];
    if (resolvedKey !== selectedKey) setSelectedKey(resolvedKey);
  }, [order, resolvedKey, selectedKey]);

  return (
    <div className="grid items-start gap-3 lg:grid-cols-[minmax(0,1fr)_364px]">
      <div data-tour="sales.calling.queue" className="min-w-0 overflow-hidden rounded-lg border border-border bg-card">
        {SECTION_ORDER.filter((section) => queue[section].length > 0).map((section) => (
          <section key={section} aria-label={SECTION_TITLES[section]}>
            <header className="flex items-baseline justify-between gap-3 border-b border-border bg-muted/40 px-3 py-1">
              <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {SECTION_TITLES[section]}
              </h2>
              {sectionHint(queue, section) && (
                <span className="text-xs text-muted-foreground">{sectionHint(queue, section)}</span>
              )}
            </header>
            <ul className="divide-y divide-border border-b border-border">
              {queue[section].map((item) => (
                <QueueRow
                  key={item.key}
                  item={item}
                  today={queue.today}
                  active={selected?.key === item.key}
                  onSelect={() => setSelectedKey(item.key)}
                />
              ))}
            </ul>
          </section>
        ))}
        <p className="px-3 py-1.5 text-xs text-muted-foreground">
          „Oddzwonić”, „Nie teraz” i „Nie zainteresowany” wracają tu same w wybranym dniu.
        </p>
      </div>
      {selected && (
        <div className="lg:sticky lg:top-2 lg:max-h-[calc(100dvh-1rem)] lg:overflow-y-auto">
          <CallCard
            key={selected.key}
            item={selected}
            position={`${selectedIndex + 1} z ${items.length}`}
            today={queue.today}
            nextCompany={upcoming?.company.name ?? null}
            canEdit={canEdit}
            meetingStage={meetingStage}
            onSaved={() => setSelectedKey(upcomingKey)}
          />
        </div>
      )}
    </div>
  );
}

/**
 * Akcje nagłówka: kampanie i import listy, tylko dla „Sprzedaż: edycja”. Stoją w linii
 * opisu ramy Sprzedaży, żeby nie zabierać kolejce wiersza na ekranie 720 px.
 */
export function CallingActions() {
  const user = useAuthStore((s) => s.user);
  const [importOpen, setImportOpen] = useState(false);
  const [campaignsOpen, setCampaignsOpen] = useState<"list" | "new" | null>(null);
  const [excelOpen, setExcelOpen] = useState(false);
  if (!hasPermission(user, "sales_edit")) return null;
  return (
    <>
      <Button size="sm" variant="outline" className="h-7" onClick={() => setCampaignsOpen("list")}>
        Kampanie
      </Button>
      <Button
        size="sm"
        variant="outline"
        className="h-7"
        data-tour="sales.calling.import"
        onClick={() => setImportOpen(true)}
      >
        <Upload className="mr-1.5 h-3.5 w-3.5" aria-hidden /> Importuj listę
      </Button>
      {importOpen && (
        <ImportListDialog
          open
          onOpenChange={setImportOpen}
          onNewCampaign={() => setCampaignsOpen("new")}
          onExcel={() => {
            setImportOpen(false);
            setExcelOpen(true);
          }}
        />
      )}
      {excelOpen && <ExcelTransferDialog open onOpenChange={setExcelOpen} />}
      {campaignsOpen && (
        <CampaignsDialog
          key={campaignsOpen}
          open
          startNew={campaignsOpen === "new"}
          onOpenChange={(open) => !open && setCampaignsOpen(null)}
        />
      )}
    </>
  );
}

/** Zakładka „Dzwonienie”: jedna lista w stałej kolejności i karta wybranej pozycji. */
export function CallQueueView() {
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const [campaignId, setCampaignId] = useState<number | null>(null);
  const [view, setView] = useState<"queue" | "table">("queue");
  const query = useCallQueue(campaignId);
  const pipelines = usePipelines();

  const sales = pipelines.data?.find((pipeline) => pipeline.key === SALES_PIPELINE_KEY);
  const stage = sales?.stages.find((item) => item.key === MEETING_STAGE_KEY);
  const meetingStage: MeetingStage | null = sales && stage ? { pipelineId: sales.id, stageId: stage.id } : null;

  const state = resolveViewState({
    isLoading: query.isLoading,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: false,
  });

  if (state === "loading") return <p className="py-6 text-sm text-muted-foreground">Wczytywanie kolejki…</p>;
  if (state !== "ready" || !query.data) {
    return (
      <QueryStateNotice
        state={state === "ready" || state === "empty" ? "error" : state}
        onRetry={() => void query.refetch()}
      />
    );
  }

  const queue = query.data;
  return (
    <div className="space-y-2">
      <div className="flex min-h-7 flex-wrap items-center justify-between gap-x-4 gap-y-1 text-sm">
        <p className="min-w-0 text-muted-foreground">
          <span className="font-medium text-foreground">{dayHeading(queue.today)}:</span> {queueLine(queue)}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <CampaignFilter queue={queue} value={campaignId} onChange={setCampaignId} />
          <span data-tour="sales.calling.view">
            <SegmentedRadio
              label="Widok"
            size="sm"
            value={view}
            onChange={setView}
            options={[
              { value: "queue", label: "Kolejka" },
              { value: "table", label: "Tabela" },
              ]}
            />
          </span>
        </div>
      </div>
      {/* Licznik bez celu (decyzja Artura 11.11.2026): zastępuje ręczne „Podsumowanie” w Excelu. */}
      <p className="text-xs text-muted-foreground" aria-label="Dziś" data-tour="sales.calling.today">
        <span className="font-medium text-foreground">Dziś:</span> {dayLine(queue.today_counts)}
        <span className="mx-1.5" aria-hidden>
          ·
        </span>
        {formatWeekdayDayPl(queue.yesterday)}: {dayLine(queue.yesterday_counts)}
      </p>
      {view === "table" ? (
        <CallTableView today={queue.today} campaignId={campaignId} canEdit={canEdit} meetingStage={meetingStage} />
      ) : isQueueEmpty(queue) ? (
        <div className="rounded-lg border border-border bg-card">
          <EmptyState
            icon={PhoneCall}
            title="Kolejka jest pusta."
            description={
              queue.counts.later > 0
                ? "Na dziś nic nie zostało. Oddzwonienia z datą wrócą tu same w swoim dniu."
                : "Zaimportuj listę do kampanii, a rekordy pojawią się tutaj. Oddzwonienia wracają same w wybranym dniu."
            }
          />
        </div>
      ) : (
        <QueueBoard queue={queue} canEdit={canEdit} meetingStage={meetingStage} />
      )}
    </div>
  );
}
