"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { apiErrorMessage } from "@/lib/api-error";
import {
  getCalendar,
  getClientCatalog,
  shortDate,
  type CalendarItem,
  type ReportDefinition,
} from "@/lib/api/client-reports";
import { ReportDownloadDialog } from "./ReportDownloadDialog";
import { ReportStateDot } from "./ReportStateDot";

type Kind = "all" | "management" | "settlement";

const MONTHS = [
  "Styczeń",
  "Luty",
  "Marzec",
  "Kwiecień",
  "Maj",
  "Czerwiec",
  "Lipiec",
  "Sierpień",
  "Wrzesień",
  "Październik",
  "Listopad",
  "Grudzień",
];

export function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split("-").map(Number);
  const index = y * 12 + (m - 1) + delta;
  return `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, "0")}`;
}

function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

/** Tryb „Raporty dla klientów” w module Klienci: co i komu w miesiącu. */
export function ReportsCalendarPanel({ defaultMine = false }: { defaultMine?: boolean }) {
  const [month, setMonth] = useState(currentMonth);
  const [mine, setMine] = useState(defaultMine);
  const [kind, setKind] = useState<Kind>("all");
  const [open, setOpen] = useState<{ definition: ReportDefinition; period: string; canEdit: boolean } | null>(null);
  const [opening, setOpening] = useState<number | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);

  const query = useQuery({ queryKey: ["client-reports-calendar", month, mine], queryFn: () => getCalendar(month, mine) });
  const pick = (items: CalendarItem[]) => items.filter((i) => kind === "all" || i.family === kind);
  const items = pick(query.data?.items ?? []);
  const upcoming = pick(query.data?.upcoming ?? []);
  const counts = query.data?.counts ?? {};
  const [y, m] = month.split("-").map(Number);

  const openItem = async (item: CalendarItem) => {
    setOpening(item.definition_id);
    setOpenError(null);
    try {
      const catalog = await getClientCatalog(item.client_id);
      const definition = catalog.definitions.find((d) => d.id === item.definition_id);
      if (definition) setOpen({ definition, period: item.period_key, canEdit: catalog.can_edit });
    } catch (error) {
      setOpenError(apiErrorMessage(error, "Nie udało się otworzyć raportu."));
    } finally {
      setOpening(null);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-1">
          <Button size="icon-sm" variant="ghost" aria-label="Poprzedni miesiąc" onClick={() => setMonth((v) => shiftMonth(v, -1))}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <h2 className="min-w-36 text-center font-display text-base font-semibold text-foreground">
            {MONTHS[m - 1]} {y}
          </h2>
          <Button size="icon-sm" variant="ghost" aria-label="Następny miesiąc" onClick={() => setMonth((v) => shiftMonth(v, 1))}>
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
        <InlineStats
          stats={[
            { id: "over", label: "po terminie", value: counts.overdue ?? 0 },
            { id: "todo", label: "do przygotowania", value: (counts.todo ?? 0) + (counts.today ?? 0) },
            { id: "nodate", label: "bez terminu", value: counts.no_date ?? 0 },
            { id: "sent", label: "wysłane", value: counts.sent ?? 0 },
          ]}
        />
        <div className="flex flex-wrap gap-2">
          <Segmented
            label="Czyje raporty"
            value={mine ? "mine" : "all"}
            onChange={(v) => setMine(v === "mine")}
            options={[
              { value: "mine", label: "Moje" },
              { value: "all", label: "Wszystkie" },
            ]}
          />
          <Segmented
            label="Rodzaj raportów"
            value={kind}
            onChange={setKind}
            options={[
              { value: "all", label: "Wszystkie" },
              { value: "management", label: "Zarządcze" },
              { value: "settlement", label: "Rozliczenia" },
            ]}
          />
        </div>
      </div>

      {openError ? <p className="text-sm text-destructive">{openError}</p> : null}
      {query.isLoading ? <p className="text-sm text-muted-foreground">Wczytuję terminy…</p> : null}
      {query.isError ? <QueryStateNotice state="error" description={apiErrorMessage(query.error, "Nie udało się wczytać kalendarza raportów.")} onRetry={() => void query.refetch()} /> : null}
      {query.isSuccess ? (
        <>
          <CalendarTable items={items} month={month} onOpen={openItem} opening={opening} empty={mine ? "Nic do wysłania w tym miesiącu po Twojej stronie." : "Nic do wysłania w tym miesiącu."} />
          {upcoming.length > 0 ? (
            <>
              <h3 className="pt-2 text-xs font-semibold text-muted-foreground">Dalej: kwartalne i roczne</h3>
              <CalendarTable items={upcoming} month={month} onOpen={openItem} opening={opening} empty="" />
            </>
          ) : null}
        </>
      ) : null}

      <ReportDownloadDialog
        definition={open?.definition ?? null}
        initialPeriod={open?.period}
        canEdit={Boolean(open?.canEdit)}
        onClose={() => {
          setOpen(null);
          void query.refetch();
        }}
      />
    </div>
  );
}

function CalendarTable({
  items,
  month,
  onOpen,
  opening,
  empty,
}: {
  items: CalendarItem[];
  month: string;
  onOpen: (item: CalendarItem) => void;
  opening: number | null;
  empty: string;
}) {
  if (items.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border p-4 text-center text-sm text-muted-foreground">{empty}</p>
    );
  }
  return (
    <div className="relative overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-[820px] text-sm">
        <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
          <tr>
            <th className="w-24 px-3 py-2 font-medium">Termin</th>
            <th className="px-3 py-2 font-medium">Klient</th>
            <th className="px-3 py-2 font-medium">Raport · okres</th>
            <th className="px-3 py-2 font-medium">Przygotowuje</th>
            <th className="px-3 py-2 font-medium">Stan</th>
            <th className="px-3 py-2">
              <span className="sr-only">Akcje</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {items.map((item) => (
            <tr key={`${item.definition_id}-${item.period_key}`} className="h-11">
              <td className="px-3 py-1.5 tabular-nums text-foreground">{shortDate(item.due, month)}</td>
              <td className="px-3 py-1.5">
                <Link href={`/clients/${item.client_id}?tab=raporty`} className="text-foreground hover:underline">
                  {item.client_name}
                </Link>
              </td>
              <td className="px-3 py-1.5">
                <div className="text-foreground">{item.report}</div>
                <div className="text-xs text-muted-foreground">
                  {item.period_label}
                  {item.carried ? " · zaległy z poprzedniego miesiąca" : ""}
                </div>
              </td>
              <td className="px-3 py-1.5 text-xs text-foreground">{item.preparer_label}</td>
              <td className="px-3 py-1.5 text-xs">
                <ReportStateDot state={item.state} />
              </td>
              <td className="px-3 py-1.5 text-right">
                {item.family === "settlement" && !item.has_generator ? (
                  <Button size="sm" variant="ghost" asChild>
                    <Link href={`/finance?view=settlements&stClient=${item.client_id}`}>Rozliczenia →</Link>
                  </Button>
                ) : (
                  <Button size="sm" variant="outline" onClick={() => onOpen(item)} loading={opening === item.definition_id}>
                    <FileText className="h-3.5 w-3.5" aria-hidden="true" /> {item.has_generator ? "Pobierz" : "Wysyłka"}
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Segmented<T extends string>({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-md border border-border p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={`h-7 rounded px-2.5 text-xs ${
            o.value === value ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
