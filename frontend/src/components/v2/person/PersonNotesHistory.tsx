"use client";

/**
 * Notatki osoby w panelu rekrutacji (12.10.2026): „W tej rekrutacji” oraz
 * „Wcześniej u nas” — notatki z innych rekrutacji i bez rekrutacji,
 * pogrupowane po rekrutacji, z jej wynikiem z historii osoby.
 *
 * Do tej daty zakładka „Notatki i historia” i sekcja „Notatki” doku pytały
 * tylko o `job_id` bieżącej rekrutacji, więc osoba z bogatą historią wyglądała
 * jak ktoś, o kim nic nie wiemy. Jedno zapytanie o wszystkie notatki osoby
 * (ten sam klucz co „Historia” profilu), podział liczy `notes-by-recruitment`.
 * Trzeci wariant, `reader`, to „Historia osoby” w dużej strefie podglądu:
 * wszystkie notatki osoby naraz (także z tej rekrutacji), z filtrem rodzajów.
 * Listę rysuje ta sama `NotesList` co w profilu — odpowiedzi, przypięte,
 * zwijanie długich treści i zakryte wpisy o stawce działają tu bez kopii.
 *
 * Wynik rekrutacji to dodatek: gdy historia się nie wczyta albo nie zna
 * rekrutacji z notatki, grupa zostaje bez plakietki. Awaria notatek to jeden
 * komunikat z „Ponów” — nigdy pusty stan.
 */

import { useId, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { JobNotesList } from "@/components/v2/candidate-profile/JobNotesList";
import { DockLoadError } from "@/components/v2/jobs/workbench-chrome";
import { candidateNoteItems, useCandidateNotes } from "@/components/v2/pages/candidate-notes-query";
import { useCandidateRecruitmentOutcomes } from "@/components/v2/pages/candidate-outcomes-query";
import { NOTE_GROUP_EMPTY_TEXT, NOTE_GROUPS, noteGroupCounts } from "@/lib/candidate-note-groups";
import { cn } from "@/lib/utils";

import {
  earlierSummaryLabel,
  groupFactsLine,
  NOTES_FILTER_LABEL,
  notesCountLabel,
  notesForFilter,
  splitPersonNotes,
  THIS_RECRUITMENT_KEY,
  type EarlierNotesFilter,
  type EarlierNotesGroup,
} from "./notes-by-recruitment";

/* eslint-disable @typescript-eslint/no-explicit-any -- notatki z luźno typowanego endpointu */

/** Ile ostatnich rozmów spoza rekrutacji pokazuje wąski dok. */
const DOCK_TEASER_NOTES = 2;

export interface PersonNotesHistoryProps {
  candidateId: number;
  jobId: number;
  readOnly: boolean;
  /**
   * `tab` — zakładka „Notatki i historia”; `dock` — sekcja „Notatki” wąskiego
   * doku; `reader` — „Historia osoby” w dużej strefie podglądu.
   */
  variant?: "tab" | "dock" | "reader";
  /** Dok: „Cała historia (M)” otwiera zakładkę w rozwiniętym panelu. */
  onOpenHistory?: () => void;
}

function SectionHead({ title, meta }: { title: string; meta?: string | null }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <h3 className="text-xs font-semibold text-muted-foreground">{title}</h3>
      {meta ? <span className="text-xs text-muted-foreground">{meta}</span> : null}
    </div>
  );
}

function FilterSwitch({
  filter,
  talks,
  all,
  onChange,
}: {
  filter: EarlierNotesFilter;
  talks: number;
  all: number;
  onChange: (next: EarlierNotesFilter) => void;
}) {
  const options: ReadonlyArray<{ value: EarlierNotesFilter; label: string; count: number }> = [
    { value: "talks", label: "Rozmowy", count: talks },
    { value: "all", label: "Wszystko", count: all },
  ];
  return (
    <div
      role="group"
      aria-label="Które notatki pokazać"
      className="inline-flex w-fit rounded-md border border-border bg-muted/30 p-0.5"
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={filter === option.value}
          onClick={() => onChange(option.value)}
          className={cn(
            "rounded px-2.5 py-1 text-xs font-medium transition-colors pointer-coarse:py-2",
            filter === option.value
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {option.label} <span className="tabular-nums text-muted-foreground">{option.count}</span>
        </button>
      ))}
    </div>
  );
}

function groupLabel(group: EarlierNotesGroup<unknown>): string {
  if (group.key === THIS_RECRUITMENT_KEY) return "Ta rekrutacja";
  return group.jobId == null ? "Notatki bez rekrutacji" : `Rekrutacja: ${group.title}`;
}

function GroupCard({
  group,
  filter,
  open,
  onToggle,
  onShowAll,
  candidateId,
  readOnly,
}: {
  group: EarlierNotesGroup<any>;
  filter: EarlierNotesFilter;
  open: boolean;
  /** Brak = grupa zawsze rozwinięta (czytnik), nagłówek nie jest przyciskiem. */
  onToggle?: () => void;
  onShowAll: () => void;
  candidateId: number;
  readOnly: boolean;
}) {
  const bodyId = useId();
  const notes = useMemo(() => notesForFilter(group.notes, filter), [group.notes, filter]);
  const head = (
    <>
      <span className="min-w-0 flex-1">
        <span className="font-medium text-foreground">{group.title}</span>
        {group.clientName ? <span className="text-xs text-muted-foreground"> · {group.clientName}</span> : null}
        {group.period ? (
          <span className="whitespace-nowrap text-xs text-muted-foreground"> · {group.period}</span>
        ) : null}
        <span className="block text-xs text-muted-foreground">{groupFactsLine(group)}</span>
      </span>
      {group.outcome ? (
        <Badge size="sm" variant={group.outcome.tone} className="mt-0.5 shrink-0">
          {group.outcome.label}
        </Badge>
      ) : null}
    </>
  );
  return (
    <article aria-label={groupLabel(group)} className="rounded-lg border border-border bg-card">
      {onToggle ? (
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          aria-controls={bodyId}
          className="flex w-full items-start gap-2 px-3 py-2 text-left"
        >
          {open ? (
            <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
          ) : (
            <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
          )}
          {head}
        </button>
      ) : (
        <div className="flex items-start gap-2 px-3 py-2">{head}</div>
      )}
      {open ? (
        <div id={bodyId} className="px-3 pb-3">
          {notes.length === 0 && filter !== "all" ? (
            <p className="text-xs text-muted-foreground">
              {NOTE_GROUP_EMPTY_TEXT[filter]}{" "}
              <button type="button" className="font-medium text-primary hover:underline" onClick={onShowAll}>
                Pokaż wszystko ({group.notes.length})
              </button>
            </p>
          ) : (
            <JobNotesList
              candidateId={candidateId}
              notes={notes}
              readOnly={readOnly}
              includeSystem={filter === "all" || filter === "automat"}
            />
          )}
        </div>
      ) : null}
    </article>
  );
}

export function PersonNotesHistory({
  candidateId,
  jobId,
  readOnly,
  variant = "tab",
  onOpenHistory,
}: PersonNotesHistoryProps) {
  const notesQuery = useCandidateNotes(candidateId);
  // Wyniki rekrutacji czytają zakładka i czytnik — dok pokazuje sam skrót rozmów.
  const outcomesQuery = useCandidateRecruitmentOutcomes(candidateId, variant !== "dock");
  const split = useMemo(
    () => splitPersonNotes<any>(candidateNoteItems(notesQuery.data), jobId, outcomesQuery.data),
    [notesQuery.data, jobId, outcomesQuery.data],
  );

  const talks = useMemo(() => notesForFilter(split.earlier, "talks"), [split.earlier]);
  const [pickedFilter, setPickedFilter] = useState<EarlierNotesFilter | null>(null);
  // Osoba, z którą nikt jeszcze nie rozmawiał (same próby kontaktu, wpisy DL):
  // „Rozmowy” byłyby puste, więc od razu pokazujemy wszystko.
  const filter: EarlierNotesFilter = pickedFilter ?? (talks.length > 0 ? "talks" : "all");
  // `null` = użytkownik nic nie zwijał: otwarta jest najświeższa grupa, która
  // ma co pokazać przy bieżącym filtrze. Sama najświeższa bywa rekrutacją
  // z jedną próbą kontaktu — otwierałaby się na „Brak notatek z rozmów”.
  const [openGroups, setOpenGroups] = useState<ReadonlySet<string> | null>(null);
  const defaultOpenKey = (
    split.groups.find((group) => notesForFilter(group.notes, filter).length > 0) ?? split.groups[0]
  )?.key;
  const isOpen = (key: string) => (openGroups ? openGroups.has(key) : key === defaultOpenKey);
  const toggleGroup = (key: string) => {
    const next = new Set(openGroups ?? (defaultOpenKey ? [defaultOpenKey] : []));
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setOpenGroups(next);
  };

  if (notesQuery.isLoading) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground" role="status">
        <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> Wczytywanie…
      </div>
    );
  }
  if (notesQuery.isError) {
    return <DockLoadError what="notatki" onRetry={() => void notesQuery.refetch()} />;
  }
  if (!notesQuery.isSuccess) return null;

  if (variant === "reader") {
    const items = candidateNoteItems(notesQuery.data);
    const counts = noteGroupCounts(notesQuery.data?.group_counts, items);
    const total = NOTE_GROUPS.reduce((sum, group) => sum + counts[group], 0);
    const readerFilter: EarlierNotesFilter = pickedFilter ?? (counts.talks > 0 ? "talks" : "all");
    // Rodzaj bez notatek nie dostaje pigułki — chyba że jest właśnie wybrany.
    const options: EarlierNotesFilter[] = [
      ...NOTE_GROUPS.filter((group) => counts[group] > 0 || readerFilter === group),
      "all",
    ];
    const groups = [split.hereGroup, ...split.groups].filter(
      (group): group is EarlierNotesGroup<any> =>
        group != null && notesForFilter(group.notes, readerFilter).length > 0,
    );
    return (
      <div className="mx-auto max-w-4xl space-y-3 text-[13px]">
        <div role="group" aria-label="Rodzaj notatek" className="flex flex-wrap gap-1.5">
          {options.map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={readerFilter === option}
              onClick={() => setPickedFilter(option)}
              className={cn(
                "rounded-full border px-2.5 py-1 text-xs font-medium transition-colors pointer-coarse:py-2",
                readerFilter === option
                  ? "border-primary/40 bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {NOTES_FILTER_LABEL[option]}{" "}
              <span className="tabular-nums">{option === "all" ? total : counts[option]}</span>
            </button>
          ))}
        </div>
        {groups.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            {readerFilter === "all" ? "Brak notatek o tej osobie." : NOTE_GROUP_EMPTY_TEXT[readerFilter]}
          </p>
        ) : (
          groups.map((group) => (
            <GroupCard
              key={group.key}
              group={group}
              filter={readerFilter}
              open
              onShowAll={() => setPickedFilter("all")}
              candidateId={candidateId}
              readOnly={readOnly}
            />
          ))
        )}
      </div>
    );
  }

  if (variant === "dock") {
    const teaser = (talks.length > 0 ? talks : split.earlier.filter((note) => !note.is_system))
      .slice()
      .sort((a, b) => Date.parse(b.created_at ?? "") - Date.parse(a.created_at ?? ""))
      .slice(0, DOCK_TEASER_NOTES);
    return (
      <div className="space-y-3">
        {split.here.length === 0 && split.earlierHuman > 0 ? (
          <p className="text-xs text-muted-foreground">W tej rekrutacji jeszcze nic nie zapisano.</p>
        ) : (
          <JobNotesList candidateId={candidateId} notes={split.here} readOnly={readOnly} />
        )}
        {teaser.length > 0 ? (
          <section aria-label="Wcześniej u nas" className="space-y-2">
            <SectionHead title="Wcześniej u nas" meta="ostatnie rozmowy" />
            <JobNotesList candidateId={candidateId} notes={teaser} readOnly={readOnly} showRecruitment />
            {onOpenHistory ? (
              <Button size="sm" variant="outline" className="w-full" onClick={onOpenHistory}>
                Cała historia ({split.earlierHuman})
              </Button>
            ) : null}
          </section>
        ) : null}
      </div>
    );
  }

  return (
    <div className="space-y-4 text-[13px]">
      <section aria-label="Notatki w tej rekrutacji" className="space-y-2">
        <SectionHead title="W tej rekrutacji" meta={notesCountLabel(split.hereHuman)} />
        {split.here.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            Jeszcze nic nie zapisano.{readOnly ? "" : " Pierwsza notatka z pola na dole trafi tutaj."}
          </p>
        ) : (
          <JobNotesList candidateId={candidateId} notes={split.here} readOnly={readOnly} />
        )}
      </section>

      <section aria-label="Wcześniej u nas" className="space-y-2">
        <SectionHead
          title="Wcześniej u nas"
          meta={split.earlier.length > 0 ? earlierSummaryLabel(split) : null}
        />
        {split.earlier.length === 0 ? (
          <p className="text-xs text-muted-foreground">Nie ma wcześniejszych notatek o tej osobie.</p>
        ) : (
          <>
            {talks.length > 0 && talks.length < split.earlier.length ? (
              <FilterSwitch
                filter={filter}
                talks={talks.length}
                all={split.earlier.length}
                onChange={setPickedFilter}
              />
            ) : null}
            {split.groups.map((group) => (
              <GroupCard
                key={group.key}
                group={group}
                filter={filter}
                open={isOpen(group.key)}
                onToggle={() => toggleGroup(group.key)}
                onShowAll={() => setPickedFilter("all")}
                candidateId={candidateId}
                readOnly={readOnly}
              />
            ))}
          </>
        )}
      </section>
    </div>
  );
}
