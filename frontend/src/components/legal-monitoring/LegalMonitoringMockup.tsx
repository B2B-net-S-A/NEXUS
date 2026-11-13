"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";

import { DataTable, type DataTableColumn } from "@/components/ds/DataTable";
import { DetailPanel } from "@/components/ds/DetailPanel";
import { FilterBar } from "@/components/ds/FilterBar";
import { ListDetailLayout } from "@/components/ds/ListDetailLayout";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { formatIsoDatePl } from "@/lib/date-pl";

// MAKIETA: pozycje z Compassa (eksport 13.11.2026) z pliku lokalnego, bez API.

type Severity = "red" | "yellow" | "green";
type Status = "new" | "reviewed" | "action_required" | "dismissed";
type SourceHealth = "ok" | "empty" | "fail";

interface Item {
  id: string;
  source: string;
  source_label: string;
  topic: string;
  severity: Severity;
  published_at: string | null;
  reference: string | null;
  title: string;
  url: string | null;
  summary: string;
  why_it_matters: string;
  status: Status;
  created_at: string;
}

interface Run {
  run_at: string;
  status: "ok" | "partial" | "failed";
  items_found: number;
  sources_checked: Record<string, SourceHealth>;
}

const SEVERITY: Record<Severity, { label: string; tone: StatusDotTone; rank: number }> = {
  red: { label: "Może wymagać decyzji", tone: "danger", rank: 0 },
  yellow: { label: "Do omówienia", tone: "warning", rank: 1 },
  green: { label: "Kontekst", tone: "neutral", rank: 2 },
};

const STATUS: Record<Status, { label: string; variant: "info" | "success" | "danger" | "neutral" }> = {
  new: { label: "Do przejrzenia", variant: "info" },
  reviewed: { label: "Przejrzane", variant: "success" },
  action_required: { label: "Do reakcji", variant: "danger" },
  dismissed: { label: "Nieistotne", variant: "neutral" },
};

const TOPICS: Record<string, string> = {
  pip_b2b: "B2B a art. 22 KP",
  cit_estonski: "Estoński CIT",
  zus_samozatrudnienie: "ZUS",
  legislacja: "Legislacja",
  tk_pip: "TK, ustawa o PIP",
};

const SOURCES: Record<string, string> = {
  GIP: "PIP/GIP",
  EUREKA: "Interpretacje KIS",
  SN: "Sąd Najwyższy",
  NSA_WSA: "NSA/WSA",
  ZUS: "ZUS",
  SEJM_RCL: "Sejm/RCL",
  TK: "TK",
  PRASA: "Prasa",
};

const HOLIDAYS = new Set(["2026-11-01", "2026-11-11"]);
const TODAY = "2026-11-13";

function workingDaysAfter(lastIso: string, todayIso: string): number {
  let n = 0;
  const d = new Date(`${lastIso}T12:00:00Z`);
  const end = new Date(`${todayIso}T12:00:00Z`);
  for (d.setUTCDate(d.getUTCDate() + 1); d <= end; d.setUTCDate(d.getUTCDate() + 1)) {
    const iso = d.toISOString().slice(0, 10);
    const wd = d.getUTCDay();
    if (wd !== 0 && wd !== 6 && !HOLIDAYS.has(iso)) n += 1;
  }
  return n;
}

function HealthLine({ runs }: { runs: Run[] }) {
  const last = runs[0];
  if (!last) return null;
  const lastDay = last.run_at.slice(0, 10);
  const missed = workingDaysAfter(lastDay, TODAY);
  if (missed >= 1) {
    return (
      <Alert
        variant="error"
        title={`Automat nie sprawdza źródeł od ${formatIsoDatePl(lastDay)}: ${missed} dni roboczych bez przebiegu.`}
        description="Nowe orzeczenia i interpretacje nie trafiają na listę. Administratorzy dostali alert mailem."
      />
    );
  }
  return null;
}

function RunsTable({ runs }: { runs: Run[] }) {
  const columns: Array<DataTableColumn<Run>> = [
    {
      key: "at",
      header: "Sprawdzenie",
      render: (r) => <span className="whitespace-nowrap">{formatIsoDatePl(r.run_at)}</span>,
    },
    {
      key: "found",
      header: "Nowe pozycje",
      align: "right",
      render: (r) => r.items_found,
    },
    {
      key: "sources",
      header: "Źródła niedostępne",
      render: (r) => {
        const failed = Object.entries(r.sources_checked)
          .filter(([, h]) => h === "fail")
          .map(([s]) => SOURCES[s] ?? s);
        return failed.length ? (
          <span className="text-warning-muted-foreground">{failed.join(", ")}</span>
        ) : (
          <span className="text-muted-foreground">wszystkie odpowiedziały</span>
        );
      },
    },
  ];
  return (
    <div className="space-y-2">
      <p className="text-sm text-muted-foreground">
        Jedno źródło niedostępne to zwykle chwilowa awaria strony urzędu. Alert idzie dopiero
        po trzech sprawdzeniach z rzędu.
      </p>
      <DataTable columns={columns} rows={runs} getRowKey={(r) => r.run_at} empty="Automat nie zgłosił jeszcze żadnego sprawdzenia." />
    </div>
  );
}

function ItemPanel({
  item,
  onClose,
  onDecide,
}: {
  item: Item;
  onClose: () => void;
  onDecide: (status: Status) => void;
}) {
  const [note, setNote] = useState("");
  const sev = SEVERITY[item.severity];
  return (
    <DetailPanel
      title={item.title}
      badges={<Badge variant={STATUS[item.status].variant}>{STATUS[item.status].label}</Badge>}
      subtitle={[
        item.source_label,
        item.reference,
        item.published_at ? `dokument z ${formatIsoDatePl(item.published_at)}` : null,
      ]
        .filter(Boolean)
        .join(" · ")}
      onClose={onClose}
      footer={
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => onDecide("reviewed")}>Przejrzane</Button>
          <Button size="sm" variant="outline" onClick={() => onDecide("action_required")}>Do reakcji</Button>
          <Button size="sm" variant="ghost" onClick={() => onDecide("dismissed")}>Nieistotne</Button>
        </div>
      }
    >
      <div className="space-y-4 px-4 py-3 text-sm">
        <StatusDot tone={sev.tone}>{sev.label}</StatusDot>
        <section className="space-y-1">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Co się stało</h3>
          <p className="whitespace-pre-line">{item.summary}</p>
        </section>
        <section className="space-y-1">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Dlaczego to ważne dla nas</h3>
          <p className="whitespace-pre-line">{item.why_it_matters}</p>
        </section>
        {item.url && (
          <a href={item.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
            Otwórz źródło <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
          </a>
        )}
        <section className="space-y-1">
          <label htmlFor="legal-note" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Notatka do decyzji (opcjonalnie)
          </label>
          <Textarea id="legal-note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Np. omówić na spotkaniu zarządu" />
        </section>
      </div>
    </DetailPanel>
  );
}

export function LegalMonitoringMockup() {
  const items = useQuery({
    queryKey: ["makieta-legal-items"],
    queryFn: async () => (await fetch("/__makieta/legal_items.json")).json() as Promise<Item[]>,
  });
  const runs = useQuery({
    queryKey: ["makieta-legal-runs"],
    queryFn: async () => (await fetch("/__makieta/legal_runs.json")).json() as Promise<Run[]>,
  });
  const [tab, setTab] = useState("new");
  const [search, setSearch] = useState("");
  const [severity, setSeverity] = useState<Severity | "">("");
  const [overrides, setOverrides] = useState<Record<string, Status>>({});
  const [openId, setOpenId] = useState<string | null>(
    typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("item") : null,
  );

  const all = useMemo(
    () => (items.data ?? []).map((i) => ({ ...i, status: overrides[i.id] ?? i.status })),
    [items.data, overrides],
  );
  const counts = {
    new: all.filter((i) => i.status === "new").length,
    action_required: all.filter((i) => i.status === "action_required").length,
    all: all.length,
  };
  const q = search.trim().toLocaleLowerCase("pl");
  const rows = useMemo(() => {
    const scoped = all.filter((i) => (tab === "all" ? true : i.status === tab));
    return scoped
      .filter((i) => !severity || i.severity === severity)
      .filter((i) => !q || [i.title, i.reference, i.source_label].some((v) => v?.toLocaleLowerCase("pl").includes(q)))
      .sort((a, b) =>
        b.created_at.slice(0, 10).localeCompare(a.created_at.slice(0, 10)) ||
        SEVERITY[a.severity].rank - SEVERITY[b.severity].rank,
      );
  }, [all, tab, severity, q]);

  if (items.isError || runs.isError) {
    return <QueryStateNotice state="error" description="Nie udało się pobrać monitoringu prawnego." />;
  }
  if (!items.isSuccess || !runs.isSuccess) {
    return <p className="py-6 text-sm text-muted-foreground">Wczytywanie monitoringu…</p>;
  }

  const open = all.find((i) => i.id === openId) ?? null;
  const columns: Array<DataTableColumn<Item>> = [
    {
      key: "severity",
      header: "Pilność",
      width: "11rem",
      render: (i) => <StatusDot tone={SEVERITY[i.severity].tone}>{SEVERITY[i.severity].label}</StatusDot>,
    },
    {
      key: "title",
      header: "Pozycja",
      render: (i) => (
        <span className="block max-w-[34rem] whitespace-normal">
          <span className="font-medium text-foreground">{i.title}</span>
          <span className="mt-0.5 block text-xs text-muted-foreground">
            {[SOURCES[i.source] ?? i.source, i.reference, TOPICS[i.topic]].filter(Boolean).join(" · ")}
          </span>
        </span>
      ),
    },
    ...(tab === "all"
      ? [{ key: "status", header: "Status", render: (i: Item) => <Badge variant={STATUS[i.status].variant}>{STATUS[i.status].label}</Badge> }]
      : []),
    {
      key: "received",
      header: "Otrzymano",
      render: (i) => <span className="whitespace-nowrap text-muted-foreground">{formatIsoDatePl(i.created_at)}</span>,
    },
  ];

  const list =
    tab === "runs" ? (
      <RunsTable runs={runs.data} />
    ) : (
      <div className="space-y-3">
        <FilterBar
          search={{
            value: search,
            onChange: setSearch,
            placeholder: "Szukaj w tytule, sygnaturze, źródle",
            ariaLabel: "Szukaj w monitoringu prawnym",
            onClear: () => setSearch(""),
          }}
          filters={
            <div className="flex gap-1">
              {(["", "red", "yellow", "green"] as const).map((s) => (
                <Button key={s || "all"} size="sm" variant={severity === s ? "secondary" : "ghost"} onClick={() => setSeverity(s)}>
                  {s ? SEVERITY[s].label : "Każda pilność"}
                </Button>
              ))}
            </div>
          }
          resultCount={rows.length}
        />
        <DataTable
          columns={columns}
          rows={rows}
          getRowKey={(i) => i.id}
          onRowClick={(i) => setOpenId(i.id)}
          rowHighlighted={(i) => i.id === openId}
          empty={tab === "new" ? "Wszystko przejrzane. Nowe pozycje pojawią się po porannym sprawdzeniu." : "Brak pozycji."}
        />
      </div>
    );

  return (
    <div className="space-y-4">
      <HealthLine runs={runs.data} />
      <TabbedNav
        ariaLabel="Widoki monitoringu"
        value={tab}
        onValueChange={(v) => {
          setTab(v);
          setOpenId(null);
        }}
        tabs={[
          { value: "new", label: "Do przejrzenia", count: counts.new },
          { value: "action_required", label: "Do reakcji", count: counts.action_required },
          { value: "all", label: "Wszystkie", count: counts.all },
          { value: "runs", label: "Historia sprawdzeń" },
        ]}
      />
      <ListDetailLayout
        list={list}
        panelLabel="Szczegóły pozycji"
        onClose={() => setOpenId(null)}
        panel={
          open && tab !== "runs" ? (
            <ItemPanel
              key={open.id}
              item={open}
              onClose={() => setOpenId(null)}
              onDecide={(status) => {
                setOverrides((prev) => ({ ...prev, [open.id]: status }));
                setOpenId(null);
              }}
            />
          ) : null
        }
      />
    </div>
  );
}
