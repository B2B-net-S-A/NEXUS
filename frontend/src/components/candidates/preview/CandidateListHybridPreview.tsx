"use client";

import * as React from "react";
import {
  Bookmark,
  Briefcase,
  ChevronDown,
  Download,
  FileText,
  Link2,
  LayoutGrid,
  List,
  Mail,
  Phone,
  Plus,
  Search,
  SlidersHorizontal,
  Sparkles,
  Table2,
  Upload,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";
import { avatarTone } from "@/components/v2/pages/candidate-list-helpers";
import { StagePill } from "@/components/v2/candidates/StagePill";
import {
  type CandidateDetailData,
  CandidateDetailPanel,
} from "@/components/v2/candidates/CandidateDetailPanel";
import { CandidateRowDetail } from "@/components/v2/candidates/CandidateRowDetail";
import {
  CANDIDATE_HYBRID_FIXTURES,
  type CandidateHybridFixture,
} from "./hybrid-fixtures";

/** Shared grid template — one source of truth for the header + every row so the
 *  columns stay aligned. Kept wide with a min width so the table scrolls inside
 *  its pane when the detail panel is docked. */
const GRID_COLS =
  "2rem minmax(240px,1.4fr) minmax(180px,1fr) minmax(190px,1.1fr) minmax(190px,1fr) 88px 76px 96px 2.25rem";

function toDetail(c: CandidateHybridFixture): CandidateDetailData {
  return {
    id: c.id,
    name: c.name,
    initials: c.initials,
    role: c.role,
    location: c.location,
    phone: c.phone,
    email: c.email,
    stage: c.stage,
    stageDate: c.stageDate,
    rateLabel: c.rate,
    owner: c.owner,
    recruitments: c.recruitments,
    headline: c.headline,
    skills: c.skills,
    lastNote: c.lastNote,
    rejectionReason: c.rejectionReason,
    detailPairs: [
      { label: "Stawka", value: c.rate },
      { label: "Dostępność", value: c.availability },
      { label: "Tryb pracy", value: c.workMode },
      { label: "Angielski", value: c.english },
      { label: "Narodowość", value: c.nationality },
      { label: "Dodano", value: c.added },
    ],
  };
}

interface HybridRowProps {
  candidate: CandidateHybridFixture;
  expanded: boolean;
  selected: boolean;
  onToggle: () => void;
  onSelect: () => void;
}

function HybridRow({
  candidate: c,
  expanded,
  selected,
  onToggle,
  onSelect,
}: HybridRowProps) {
  const detail = toDetail(c);
  const topSkills = c.skills.slice(0, 3);
  const moreSkills = Math.max(0, c.skills.length - 3);

  return (
    <div
      className={cn(
        "border-b border-border/70 border-l-[3px] transition-colors",
        selected
          ? "border-l-primary bg-primary/[0.06]"
          : "border-l-transparent hover:bg-muted/50",
      )}
    >
      <div
        className="grid items-center"
        style={{ gridTemplateColumns: GRID_COLS, minHeight: 68 }}
      >
        {/* checkbox */}
        <div className="flex items-center justify-center">
          <Checkbox aria-label={`Zaznacz: ${c.name}`} />
        </div>

        {/* candidate */}
        <button
          type="button"
          onClick={onSelect}
          className="flex min-w-0 items-center gap-3 px-2 py-2 text-left"
        >
          <div
            className={cn(
              "flex size-10 shrink-0 items-center justify-center rounded-full text-[13px] font-bold",
              avatarTone(c.id),
            )}
          >
            {c.initials}
          </div>
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-foreground">
              {c.name}
            </div>
            <div className="truncate text-xs text-muted-foreground">
              {c.role} · {c.location}
            </div>
          </div>
        </button>

        {/* contact */}
        <div className="flex min-w-0 flex-col gap-1 px-2 py-2">
          <span className="flex items-center gap-1.5 text-xs tabular-nums text-foreground/70">
            <Phone aria-hidden className="size-3.5 text-muted-foreground" />
            {c.phone}
          </span>
          <span
            className="flex min-w-0 items-center gap-1.5 text-xs text-foreground/70"
            title={c.email}
          >
            <Mail aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
            <span className="truncate">{c.email}</span>
          </span>
        </div>

        {/* skills */}
        <div className="flex flex-wrap items-center gap-1.5 overflow-hidden px-2 py-2">
          {topSkills.map((s) => (
            <span
              key={s}
              className="inline-flex items-center whitespace-nowrap rounded-md border border-border bg-muted px-2 py-1 text-xs font-medium text-foreground/70"
            >
              {s}
            </span>
          ))}
          {moreSkills > 0 ? (
            <span className="inline-flex items-center whitespace-nowrap rounded-md border border-border bg-card px-2 py-1 text-xs font-medium text-muted-foreground">
              +{moreSkills}
            </span>
          ) : null}
        </div>

        {/* stage */}
        <div className="flex min-w-0 flex-col gap-1 px-2 py-2">
          <StagePill stage={c.stage} size="sm" className="self-start" />
          <span className="truncate text-[11px] text-muted-foreground">
            {c.owner} · {c.stageDate}
          </span>
          {c.rejectionReason ? (
            <span className="truncate text-[11px] text-destructive" title={c.rejectionReason}>
              {c.rejectionReason}
            </span>
          ) : null}
        </div>

        {/* rate */}
        <div className="px-2 py-2 text-sm font-semibold tabular-nums text-foreground">
          {c.rate}
        </div>

        {/* recruitments */}
        <div className="flex items-center gap-1.5 px-2 py-2 text-sm text-foreground/70">
          <Briefcase aria-hidden className="size-3.5 text-muted-foreground" />
          {c.recruitments}
        </div>

        {/* added */}
        <div className="px-2 py-2 text-xs tabular-nums text-muted-foreground">
          {c.added}
        </div>

        {/* expand toggle */}
        <div className="flex items-center justify-center">
          <button
            type="button"
            onClick={onToggle}
            aria-label={expanded ? "Zwiń szczegóły" : "Pokaż szczegóły"}
            aria-expanded={expanded}
            className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <ChevronDown
              aria-hidden
              className={cn(
                "size-4 transition-transform",
                expanded && "rotate-180",
              )}
            />
          </button>
        </div>
      </div>

      {expanded ? <CandidateRowDetail candidate={detail} /> : null}
    </div>
  );
}

export function CandidateListHybridPreview() {
  const [search, setSearch] = React.useState("");
  const [expanded, setExpanded] = React.useState<Record<string, boolean>>({});
  const [selectedId, setSelectedId] = React.useState<string | null>("dawid");

  const normalized = search.trim().toLocaleLowerCase("pl");
  const rows = CANDIDATE_HYBRID_FIXTURES.filter((c) =>
    `${c.name} ${c.role} ${c.email} ${c.location} ${c.skills.join(" ")}`
      .toLocaleLowerCase("pl")
      .includes(normalized),
  );

  const selected = React.useMemo(
    () => rows.find((c) => c.id === selectedId) ?? null,
    [rows, selectedId],
  );

  const toggle = (id: string) =>
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));

  const activeFilters = ["Java", "React", "Angular", "Fullstack", "Warszawa"];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-[0.09em] text-muted-foreground">
          Sourcing · Kandydaci
        </div>
        <div className="mt-1 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight text-foreground">
              Kandydaci
            </h1>
            <p className="mt-0.5 text-sm text-muted-foreground">
              135 kandydatów w bazie · {rows.length} pasuje do filtrów
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm">
              <Upload aria-hidden className="size-4" />
              Import CSV
            </Button>
            <Button variant="outline" size="sm">
              <Sparkles aria-hidden className="size-4" />
              Dodaj z CV
            </Button>
            <Button variant="outline" size="sm">
              <FileText aria-hidden className="size-4" />
              Bulk CV
            </Button>
            <Button variant="outline" size="sm">
              <Download aria-hidden className="size-4" />
              Eksport
            </Button>
            <Button variant="outline" size="sm">
              <Link2 aria-hidden className="size-4" />
              Wygeneruj link
            </Button>
            <Button size="sm">
              <Plus aria-hidden className="size-4" />
              Dodaj
            </Button>
          </div>
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[260px] max-w-[440px] flex-1">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Szukaj po imieniu, e-mailu, stanowisku…"
            className="h-9 w-full rounded-lg border border-border bg-muted/60 pl-9 pr-3 text-sm text-foreground outline-none transition placeholder:text-muted-foreground focus-visible:border-ring focus-visible:bg-background focus-visible:ring-2 focus-visible:ring-ring/40"
          />
        </div>
        <Button variant="outline" size="sm">
          <SlidersHorizontal aria-hidden className="size-4" />
          Filtry
          <span className="ml-1 inline-flex size-4 items-center justify-center rounded-full bg-primary text-[10px] font-bold text-primary-foreground">
            5
          </span>
        </Button>
        <Button variant="outline" size="sm">
          <Bookmark aria-hidden className="size-4" />
          Zapisane <span className="text-muted-foreground">(1)</span>
        </Button>
        <div className="flex-1" />
        <Button variant="outline" size="sm">
          Najnowsi
          <ChevronDown aria-hidden className="size-4" />
        </Button>
        <div className="flex items-center gap-0.5 rounded-lg border border-border bg-muted/60 p-0.5">
          <span className="flex size-7 items-center justify-center rounded-md bg-card text-primary shadow-sm">
            <Table2 aria-hidden className="size-4" />
          </span>
          <span className="flex size-7 items-center justify-center rounded-md text-muted-foreground">
            <List aria-hidden className="size-4" />
          </span>
          <span className="flex size-7 items-center justify-center rounded-md text-muted-foreground">
            <LayoutGrid aria-hidden className="size-4" />
          </span>
        </div>
      </div>

      {/* Active filter chips */}
      <div className="flex flex-wrap items-center gap-2">
        {activeFilters.map((f) => (
          <span
            key={f}
            className="inline-flex items-center gap-1.5 rounded-lg border border-success/25 bg-success-muted py-1 pl-2.5 pr-1.5 text-xs font-medium text-success-muted-foreground"
          >
            Wszystkie: „{f}"
            <button
              type="button"
              aria-label={`Usuń filtr ${f}`}
              className="text-success-muted-foreground/70 hover:text-success-muted-foreground"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
                <path d="m6 6 12 12M18 6 6 18" />
              </svg>
            </button>
          </span>
        ))}
        <button
          type="button"
          className="px-1.5 py-1 text-xs font-medium text-muted-foreground hover:text-destructive"
        >
          Wyczyść wszystko
        </button>
      </div>

      {/* Two-pane: table (1a) + docked panel (1b) */}
      <div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
        <div className="flex h-[660px] min-h-0">
          {/* Table region */}
          <div className="min-w-0 flex-1 overflow-auto">
            <div className="min-w-[1080px]">
              {/* header */}
              <div
                className="sticky top-0 z-10 grid border-b border-border bg-muted/70 text-[10.5px] font-semibold uppercase tracking-[0.05em] text-muted-foreground backdrop-blur"
                style={{ gridTemplateColumns: GRID_COLS }}
              >
                <div className="flex items-center justify-center py-3">
                  <Checkbox aria-label="Zaznacz wszystkich" />
                </div>
                <div className="px-2 py-3">Kandydat</div>
                <div className="px-2 py-3">Kontakt</div>
                <div className="px-2 py-3">Umiejętności</div>
                <div className="px-2 py-3">Etap w procesie</div>
                <div className="px-2 py-3">Stawka</div>
                <div className="px-2 py-3">Rekrut.</div>
                <div className="px-2 py-3">Dodano</div>
                <div className="py-3" />
              </div>

              {/* rows */}
              {rows.map((c) => (
                <HybridRow
                  key={c.id}
                  candidate={c}
                  expanded={!!expanded[c.id]}
                  selected={selectedId === c.id}
                  onToggle={() => toggle(c.id)}
                  onSelect={() => setSelectedId(c.id)}
                />
              ))}

              {rows.length === 0 ? (
                <div className="px-6 py-16 text-center">
                  <p className="font-medium text-foreground">Brak kandydatów</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Zmień wyszukiwanie lub wyczyść filtry.
                  </p>
                </div>
              ) : null}
            </div>
          </div>

          {/* Detail panel */}
          {selected ? (
            <div className="hidden w-[440px] shrink-0 border-l border-border lg:block">
              <CandidateDetailPanel
                candidate={toDetail(selected)}
                onClose={() => setSelectedId(null)}
                onOpenProfile={() => undefined}
              />
            </div>
          ) : null}
        </div>

        {/* Footer / pagination */}
        <div className="flex items-center justify-between border-t border-border px-6 py-3 text-xs text-muted-foreground">
          <span>
            Pokazano{" "}
            <strong className="text-foreground">1–{rows.length}</strong> z 135
          </span>
          <div className="flex items-center gap-1">
            <Button variant="outline" size="icon-sm" aria-label="Poprzednia strona">
              ‹
            </Button>
            <Button size="icon-sm">1</Button>
            <Button variant="outline" size="icon-sm">
              2
            </Button>
            <Button variant="outline" size="icon-sm">
              3
            </Button>
            <span className="px-1">…</span>
            <Button variant="outline" size="icon-sm">
              15
            </Button>
            <Button variant="outline" size="icon-sm" aria-label="Następna strona">
              ›
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
