"use client";

import { useId, useState, type ReactNode } from "react";
import { ChevronDown, Plus, SlidersHorizontal, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { competenceCategoriesApi, type CompetenceCategoryOut } from "@/lib/api";
import {
  AVAILABILITY_OPTIONS,
  CANDIDATE_STATUS_OPTIONS,
  EMPLOYMENT_OPTIONS,
  OPEN_TO_OPTIONS,
} from "@/lib/filter-options";
import {
  parseRateBound,
  parseYearBound,
  type CandidateFilters,
  type RemoteMode,
} from "@/lib/url-filters";
import {
  LANGUAGE_LEVELS,
  LANGUAGE_OPTIONS,
  formatLanguageFilter,
  languageLabel,
  levelLabel,
  parseLanguageFilter,
  type LanguageLevelValue,
} from "@/lib/candidate-languages";
import type { SkillBucketsValue } from "@/lib/candidate-search-semantics";
import { PillGroup, toggleInList } from "@/components/v2/candidates/filters/FilterPillGroup";
import { SkillBucketsField } from "@/components/v2/candidates/SkillBucketsField";
import { HideUnknownToggle } from "@/components/v2/candidates/UnknownFieldBadges";
import { LocationInput } from "@/components/v2/filters/LocationInput";
import { TalentPoolMultiSelect } from "@/components/v2/filters/TalentPoolMultiSelect";
import { AddedByMultiSelect } from "@/components/v2/filters/AddedByMultiSelect";
import { CompanyAutocomplete } from "@/components/v2/filters/CompanyAutocomplete";
import { ClientMultiSelect } from "@/components/v2/filters/ClientMultiSelect";
import { RecruitmentMultiSelect } from "@/components/v2/filters/RecruitmentMultiSelect";
import { AdvancedSearchPopover } from "@/components/v2/filters/AdvancedSearchPopover";
import {
  StageFilterPanel,
  type StageFilterValue,
} from "@/components/v2/filters/StageFilterPanel";

const REMOTE_OPTIONS: ReadonlyArray<{ value: RemoteMode; label: string }> = [
  { value: "remote", label: "Zdalnie" },
  { value: "hybrid", label: "Hybryda" },
  { value: "onsite", label: "Biuro" },
];

const RECENTLY_CHANGED_OPTIONS = [
  { value: 1, label: "1 mies." },
  { value: 2, label: "2 mies." },
  { value: 3, label: "3 mies." },
] as const;

export interface CandidateFilterRailProps {
  filters: CandidateFilters;
  /** Łatka filtrów — wołający sam wraca na pierwszą stronę. */
  onPatch: (patch: Partial<CandidateFilters>) => void;
  /** Id zalogowanej osoby — „Moi kandydaci" = dodani przez nią. */
  currentUserId: number | null;
  skills: SkillBucketsValue;
  onSkillsChange: (next: SkillBucketsValue) => void;
  stage: StageFilterValue;
  onStageChange: (patch: Partial<StageFilterValue>) => void;
  /**
   * Frazy ALL/ANY/NONE w stanie roboczym — z pustą grupą „którakolwiek",
   * którą właśnie dodano (w `filters` puste grupy są już odfiltrowane).
   */
  phrases: { all: string[]; any: string[][]; none: string[] };
  activeCount: number;
  onClearAll: () => void;
  /** Etykieta przycisku w szufladzie „Więcej filtrów” („Pokaż 312 kandydatów”). */
  resultLabel?: string;
  className?: string;
}

/** Ten sam styl co etykiety grup „pigułek" (`PillGroup`). */
function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
      {children}
    </p>
  );
}

function FieldLabel({ children, htmlFor }: { children: ReactNode; htmlFor?: string }) {
  return (
    <label htmlFor={htmlFor} className="block text-xs text-muted-foreground">
      {children}
    </label>
  );
}

/**
 * Zwijana grupa filtrów. Domyślnie zamknięta, chyba że coś w niej jest
 * ustawione — aktywny filtr nie może się chować (wyglądałoby, że działa
 * filtr, którego nie widać).
 */
function RailGroup({
  title,
  activeCount,
  defaultOpen = false,
  children,
}: {
  title: string;
  activeCount: number;
  /** Otwarta na starcie także bez ustawionych filtrów (krótkie sekcje). */
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [manual, setManual] = useState<boolean | null>(null);
  const open = manual ?? (defaultOpen || activeCount > 0);
  const bodyId = useId();
  return (
    <section className="border-t border-border py-3 first:border-t-0 first:pt-0">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setManual(!open)}
        className="flex w-full items-center justify-between gap-2 rounded-sm text-left text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground hover:text-foreground focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="flex items-center gap-1.5">
          {title}
          {activeCount > 0 && (
            <span className="rounded-full bg-primary/10 px-1.5 text-[10px] font-medium text-primary">
              {activeCount}
            </span>
          )}
        </span>
        <ChevronDown
          className={cn("h-3.5 w-3.5 text-muted-foreground transition-transform", open && "rotate-180")}
          aria-hidden
        />
      </button>
      {open && (
        <div id={bodyId} className="mt-3 space-y-3">
          {children}
        </div>
      )}
    </section>
  );
}

function RangeInputs({
  label,
  hideLabel,
  unit,
  min,
  max,
  onChange,
  parse,
  maxValue,
}: {
  label: string;
  /** Etykieta tylko dla czytnika — nad polem stoi już tytuł sekcji. */
  hideLabel?: boolean;
  unit: string;
  min: number | null;
  max: number | null;
  onChange: (next: { min: number | null; max: number | null }) => void;
  parse: (raw: string | null) => number | null;
  maxValue?: number;
}) {
  return (
    <div className="space-y-1">
      {!hideLabel && <FieldLabel>{label}</FieldLabel>}
      <div className="flex items-center gap-1.5">
        <Input
          type="number"
          min={0}
          max={maxValue}
          aria-label={`${label} — od`}
          placeholder="od"
          value={min ?? ""}
          onChange={(e) => onChange({ min: parse(e.target.value), max })}
          className="h-8 w-full text-sm"
        />
        <span className="text-muted-foreground">–</span>
        <Input
          type="number"
          min={0}
          max={maxValue}
          aria-label={`${label} — do`}
          placeholder="do"
          value={max ?? ""}
          onChange={(e) => onChange({ min, max: parse(e.target.value) })}
          className="h-8 w-full text-sm"
        />
        <span className="shrink-0 text-xs text-muted-foreground">{unit}</span>
      </div>
    </div>
  );
}

/** Języki: każdy wiersz = kod + minimalny poziom; każdy język wymagany. */
export function LanguageFilterField({
  value,
  onChange,
}: {
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const entries = value
    .map(parseLanguageFilter)
    .filter((e): e is NonNullable<ReturnType<typeof parseLanguageFilter>> => e !== null);
  const used = new Set(entries.map((e) => e.code));
  const nextFree = LANGUAGE_OPTIONS.find((o) => !used.has(o.code));
  const update = (index: number, patch: { code?: string; level?: LanguageLevelValue | null }) =>
    onChange(
      entries.map((entry, i) =>
        formatLanguageFilter(i === index ? { ...entry, ...patch } : entry),
      ),
    );
  return (
    <div className="space-y-2">
      {entries.map((entry, index) => (
        <div key={entry.code} className="flex items-center gap-1.5">
          <select
            aria-label="Język"
            value={entry.code}
            onChange={(e) => update(index, { code: e.target.value })}
            className="h-8 min-w-0 flex-1 rounded-md border border-input bg-background px-2 text-sm text-foreground"
          >
            {LANGUAGE_OPTIONS.filter((o) => o.code === entry.code || !used.has(o.code)).map((o) => (
              <option key={o.code} value={o.code}>
                {o.label}
              </option>
            ))}
            {!LANGUAGE_OPTIONS.some((o) => o.code === entry.code) && (
              <option value={entry.code}>{languageLabel(entry.code)}</option>
            )}
          </select>
          <select
            aria-label={`Minimalny poziom: ${languageLabel(entry.code)}`}
            value={entry.level ?? ""}
            onChange={(e) =>
              update(index, { level: (e.target.value || null) as LanguageLevelValue | null })
            }
            className="h-8 w-[92px] rounded-md border border-input bg-background px-1.5 text-sm text-foreground"
          >
            <option value="">dowolny</option>
            {LANGUAGE_LEVELS.map((level) => (
              <option key={level} value={level}>
                {levelLabel(level)}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => onChange(entries.filter((_, i) => i !== index).map(formatLanguageFilter))}
            aria-label={`Usuń język: ${languageLabel(entry.code)}`}
            className="flex h-8 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
      {nextFree && entries.length < 5 && (
        <button
          type="button"
          onClick={() => onChange([...value, formatLanguageFilter({ code: nextFree.code, level: "B2" })])}
          className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
        >
          <Plus className="h-3.5 w-3.5" aria-hidden />
          Dodaj język
        </button>
      )}
      <p className="text-[11px] text-muted-foreground">Każdy wybrany język jest wymagany.</p>
    </div>
  );
}

/**
 * Lewa kolumna filtrów listy kandydatów — wariant B (makieta 22.09.2026,
 * https://claude.ai/artifact/BmwbMSuaR1stDk8G4kJVoQ). Na wierzchu tylko pięć
 * grup używanych codziennie, wszystkie rozwinięte: Kogo pokazać, Dostępność,
 * Stawka, Umiejętności, Lokalizacja. Resztę trzyma szuflada „Więcej filtrów”;
 * jej licznik mówi, ile filtrów ustawiono w środku — ukryty aktywny filtr
 * nie może wyglądać, jakby go nie było.
 */
export function CandidateFilterRail({
  filters,
  onPatch,
  currentUserId,
  skills,
  onSkillsChange,
  stage,
  onStageChange,
  phrases,
  activeCount,
  onClearAll,
  resultLabel,
  className,
}: CandidateFilterRailProps) {
  const [moreOpen, setMoreOpen] = useState(false);
  const mine =
    currentUserId !== null &&
    filters.addedByIds.length === 1 &&
    filters.addedByIds[0] === currentUserId;
  const everyone = filters.addedByIds.length === 0;

  const stageCount =
    stage.stages.length +
    (stage.currentOnly ? 1 : 0) +
    stage.clientIds.length +
    stage.movedByIds.length +
    (stage.movedAfter || stage.movedBefore ? 1 : 0);
  const historyCount =
    stageCount +
    (filters.sentToClientFrom || filters.sentToClientTo ? 1 : 0) +
    filters.workedAtClientIds.length +
    filters.recruitmentIds.length;
  const companyCount =
    filters.currentCompany.length +
    filters.pastCompany.length +
    filters.currentTitle.length +
    (filters.recentlyChangedJobs ? 1 : 0);
  const sourceCount = filters.poolIds.length + (mine ? 0 : filters.addedByIds.length);
  const statusCount = filters.status.length + filters.employment.length + filters.openTo.length;
  const experienceCount =
    (filters.experienceMin !== null || filters.experienceMax !== null ? 1 : 0) +
    (filters.hideUnknown ? 1 : 0) +
    filters.languages.length;
  const phraseCount =
    filters.qAll.length + filters.qAny.flat().length + filters.qNone.length;
  const moreCount =
    statusCount +
    experienceCount +
    filters.competenceCategoryIds.length +
    historyCount +
    companyCount +
    sourceCount +
    phraseCount;

  return (
    <aside aria-label="Filtry kandydatów" className={cn("space-y-5 text-sm", className)}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-foreground">Filtry</h2>
        {activeCount > 0 && (
          <button
            type="button"
            onClick={onClearAll}
            className="text-xs font-medium text-primary hover:underline"
          >
            Wyczyść ({activeCount})
          </button>
        )}
      </div>

      <div className="space-y-1.5">
        <SectionTitle>Kogo pokazać</SectionTitle>
        <div role="radiogroup" aria-label="Kogo pokazać" className="grid grid-cols-2 gap-1 rounded-lg bg-muted p-1">
          {[
            { key: "all", label: "Wszyscy", active: everyone, onClick: () => onPatch({ addedByIds: [] }) },
            {
              key: "mine",
              label: "Moi kandydaci",
              active: mine,
              onClick: () => currentUserId !== null && onPatch({ addedByIds: [currentUserId] }),
            },
          ].map((opt) => (
            <button
              key={opt.key}
              type="button"
              role="radio"
              aria-checked={opt.active}
              disabled={opt.key === "mine" && currentUserId === null}
              onClick={opt.onClick}
              className={cn(
                "rounded-md px-2 py-1 text-xs font-medium transition-colors disabled:opacity-50",
                opt.active
                  ? "bg-card text-foreground shadow-xs"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <p className="text-[11px] text-muted-foreground">„Moi” = dodani przez Ciebie.</p>
      </div>

      <PillGroup
        label="Dostępność"
        options={AVAILABILITY_OPTIONS}
        value={filters.availability}
        onToggle={(v) => onPatch({ availability: toggleInList(filters.availability, v) })}
      />

      <div className="space-y-1.5">
        <SectionTitle>Stawka B2B</SectionTitle>
        <RangeInputs
          label="Stawka B2B"
          hideLabel
          unit="zł/h"
          min={filters.rateMin}
          max={filters.rateMax}
          parse={parseRateBound}
          onChange={({ min, max }) => onPatch({ rateMin: min, rateMax: max })}
        />
      </div>

      <div className="space-y-1.5">
        <SectionTitle>Umiejętności</SectionTitle>
        <SkillBucketsField value={skills} onChange={onSkillsChange} compact />
      </div>

      <div className="space-y-2">
        <SectionTitle>Lokalizacja</SectionTitle>
        <LocationInput value={filters.location} onChange={(v) => onPatch({ location: v })} />
        <PillGroup
          label="Tryb pracy"
          options={REMOTE_OPTIONS}
          value={filters.remote}
          onToggle={(v) => onPatch({ remote: toggleInList(filters.remote, v) })}
        />
      </div>

      <div className="border-t border-border pt-4">
        <Button
          variant={moreCount > 0 ? "primary" : "outline"}
          className="w-full justify-between"
          onClick={() => setMoreOpen(true)}
        >
          <span className="flex items-center gap-2">
            <SlidersHorizontal className="h-4 w-4" aria-hidden />
            Więcej filtrów
          </span>
          {moreCount > 0 && (
            <span className="rounded-full bg-primary-foreground/20 px-1.5 text-xs">{moreCount}</span>
          )}
        </Button>
        <p className="mt-1.5 text-[11px] text-muted-foreground">
          Status, doświadczenie, języki, kategoria, historia z nami, firma, źródło, frazy w CV.
        </p>
      </div>

      <Sheet open={moreOpen} onOpenChange={setMoreOpen}>
        <SheetContent side="right" size="sm">
          <SheetHeader>
            <SheetTitle>Więcej filtrów</SheetTitle>
            <SheetDescription>Wyniki aktualizują się na bieżąco.</SheetDescription>
          </SheetHeader>
          <SheetBody>
            <div className="text-sm" data-testid="candidate-more-filters">
              <RailGroup title="Status i zatrudnienie" activeCount={statusCount} defaultOpen>
                <CompactPills
                  label="Status"
                  options={CANDIDATE_STATUS_OPTIONS}
                  value={filters.status}
                  onToggle={(v) => onPatch({ status: toggleInList(filters.status, v) })}
                />
                <CompactPills
                  label="Zatrudnienie"
                  options={EMPLOYMENT_OPTIONS}
                  value={filters.employment}
                  onToggle={(v) => onPatch({ employment: toggleInList(filters.employment, v) })}
                />
                <CompactPills
                  label="Otwarty na dodatkowe"
                  options={OPEN_TO_OPTIONS}
                  value={filters.openTo}
                  onToggle={(v) => onPatch({ openTo: toggleInList(filters.openTo, v) })}
                />
              </RailGroup>
              <RailGroup title="Doświadczenie i języki" activeCount={experienceCount} defaultOpen>
                <RangeInputs
                  label="Lata doświadczenia"
                  unit="lat"
                  min={filters.experienceMin}
                  max={filters.experienceMax}
                  maxValue={60}
                  parse={parseYearBound}
                  onChange={({ min, max }) => onPatch({ experienceMin: min, experienceMax: max })}
                />
                <HideUnknownToggle
                  checked={filters.hideUnknown}
                  onChange={(next) => onPatch({ hideUnknown: next })}
                />
                <div className="space-y-1">
                  <FieldLabel>Języki</FieldLabel>
                  <LanguageFilterField
                    value={filters.languages}
                    onChange={(next) => onPatch({ languages: next })}
                  />
                </div>
              </RailGroup>
              <RailGroup
                title="Kategoria kompetencji"
                activeCount={filters.competenceCategoryIds.length}
                defaultOpen
              >
                <CompetenceCategoryPills
                  value={filters.competenceCategoryIds}
                  onChange={(ids) => onPatch({ competenceCategoryIds: ids })}
                />
              </RailGroup>
              <HistoryGroup
                filters={filters}
                onPatch={onPatch}
                stage={stage}
                onStageChange={onStageChange}
                activeCount={historyCount}
              />
              <RailGroup title="Firma i stanowisko" activeCount={companyCount}>
                <CompanyFields filters={filters} onPatch={onPatch} />
              </RailGroup>
              <RailGroup title="Źródło" activeCount={sourceCount}>
                <div className="space-y-1">
                  <FieldLabel>Pula talentów</FieldLabel>
                  <TalentPoolMultiSelect value={filters.poolIds} onChange={(v) => onPatch({ poolIds: v })} />
                </div>
                <div className="space-y-1">
                  <FieldLabel>Dodany przez</FieldLabel>
                  <AddedByMultiSelect value={filters.addedByIds} onChange={(v) => onPatch({ addedByIds: v })} />
                </div>
              </RailGroup>
              <RailGroup title="Frazy w CV" activeCount={phraseCount}>
                <p className="text-[11px] text-muted-foreground">
                  Szukane w CV, notatkach i profilu. Enter lub przecinek dodaje frazę.
                </p>
                <AdvancedSearchPopover
                  value={phrases}
                  hideHeader
                  onChange={(next) => onPatch({ qAll: next.all, qAny: next.any, qNone: next.none })}
                />
              </RailGroup>
            </div>
          </SheetBody>
          <SheetFooter>
            {moreCount > 0 && (
              <Button
                variant="ghost"
                onClick={() =>
                  onPatch({
                    status: [],
                    employment: [],
                    openTo: [],
                    experienceMin: null,
                    experienceMax: null,
                    hideUnknown: false,
                    languages: [],
                    competenceCategoryIds: [],
                    qAll: [],
                    qAny: [],
                    qNone: [],
                  })
                }
              >
                Wyczyść te filtry
              </Button>
            )}
            <Button variant="primary" onClick={() => setMoreOpen(false)}>
              {resultLabel ? `Pokaż ${resultLabel}` : "Gotowe"}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </aside>
  );
}

function HistoryGroup({
  filters,
  onPatch,
  stage,
  onStageChange,
  activeCount,
}: {
  filters: CandidateFilters;
  onPatch: (patch: Partial<CandidateFilters>) => void;
  stage: StageFilterValue;
  onStageChange: (patch: Partial<StageFilterValue>) => void;
  activeCount: number;
}) {
  return (
    <RailGroup title="Historia z nami" activeCount={activeCount}>
      <div className="space-y-1">
        <FieldLabel>Etap w rekrutacji</FieldLabel>
        <StageFilterPanel value={stage} onChange={onStageChange} />
      </div>
      <div className="space-y-1">
        <FieldLabel>Wysłany do klienta</FieldLabel>
        <div className="flex items-center gap-1.5">
          <Input
            type="date"
            aria-label="Data wysłania do klienta — od"
            value={filters.sentToClientFrom}
            max={filters.sentToClientTo || undefined}
            onChange={(e) => onPatch({ sentToClientFrom: e.target.value })}
            className="h-8 text-xs"
          />
          <Input
            type="date"
            aria-label="Data wysłania do klienta — do"
            value={filters.sentToClientTo}
            min={filters.sentToClientFrom || undefined}
            onChange={(e) => onPatch({ sentToClientTo: e.target.value })}
            className="h-8 text-xs"
          />
        </div>
      </div>
      <div className="space-y-1">
        <FieldLabel>Pracował u klienta</FieldLabel>
        <ClientMultiSelect
          value={filters.workedAtClientIds}
          onChange={(v) => onPatch({ workedAtClientIds: v })}
        />
      </div>
      <div className="space-y-1">
        <FieldLabel>Rekrutacja</FieldLabel>
        <RecruitmentMultiSelect
          value={filters.recruitmentIds}
          onChange={(v) => onPatch({ recruitmentIds: v })}
        />
        {filters.recruitmentIds.length > 0 && (
          <div className="flex gap-1.5 pt-1">
            {(
              [
                { value: "assigned", label: "Przypisani" },
                { value: "not_assigned", label: "Nieprzypisani" },
              ] as const
            ).map((opt) => (
              <button
                key={opt.value}
                type="button"
                aria-pressed={filters.recruitmentMatch === opt.value}
                onClick={() => onPatch({ recruitmentMatch: opt.value })}
                className={cn(
                  "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
                  filters.recruitmentMatch === opt.value
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border bg-card text-foreground hover:bg-accent",
                )}
              >
                {opt.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </RailGroup>
  );
}

function CompanyFields({
  filters,
  onPatch,
}: {
  filters: CandidateFilters;
  onPatch: (patch: Partial<CandidateFilters>) => void;
}) {
  return (
    <>
      <div className="space-y-1">
        <FieldLabel>Obecna firma</FieldLabel>
        <CompanyAutocomplete
          value={filters.currentCompany}
          onChange={(v) => onPatch({ currentCompany: v })}
          placeholder="np. Allegro"
          suggestEndpoint="/api/candidates/companies/suggest"
        />
      </div>
      <div className="space-y-1">
        <FieldLabel>Poprzednia firma</FieldLabel>
        <CompanyAutocomplete
          value={filters.pastCompany}
          onChange={(v) => onPatch({ pastCompany: v })}
          placeholder="np. Accenture"
          suggestEndpoint="/api/candidates/companies/suggest"
        />
      </div>
      <div className="space-y-1">
        <FieldLabel>Obecne stanowisko</FieldLabel>
        <CompanyAutocomplete
          value={filters.currentTitle}
          onChange={(v) => onPatch({ currentTitle: v })}
          placeholder="np. Senior Engineer"
          suggestEndpoint="/api/candidates/titles/suggest"
        />
      </div>
      <div className="space-y-1">
        <FieldLabel>Niedawno zmienił pracę (LinkedIn)</FieldLabel>
        <div className="flex flex-wrap gap-1.5">
          {RECENTLY_CHANGED_OPTIONS.map((opt) => {
            const active = filters.recentlyChangedJobs === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                aria-pressed={active}
                onClick={() => onPatch({ recentlyChangedJobs: active ? null : opt.value })}
                className={cn(
                  "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
                  active
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border bg-card text-foreground hover:bg-accent",
                )}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      </div>
    </>
  );
}

/** Pigułki z podpisem w jednym bloku — bez nagłówka sekcji dla każdej grupy. */
function CompactPills<V extends string>({
  label,
  options,
  value,
  onToggle,
}: {
  label: string;
  options: ReadonlyArray<{ value: V; label: string }>;
  value: readonly string[];
  onToggle: (value: V) => void;
}) {
  return (
    <div className="space-y-1" role="group" aria-label={label}>
      <FieldLabel>{label}</FieldLabel>
      <div className="flex flex-wrap gap-1.5">
        {options.map((opt) => {
          const active = value.includes(opt.value);
          return (
            <button
              key={opt.value}
              type="button"
              aria-pressed={active}
              onClick={() => onToggle(opt.value)}
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
                active
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card text-foreground hover:bg-accent",
              )}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Pięć kategorii kompetencji jako pigułki (dopasowuje też kategorie poboczne). */
function CompetenceCategoryPills({
  value,
  onChange,
}: {
  value: number[];
  onChange: (ids: number[]) => void;
}) {
  const { data, isError } = useQuery<CompetenceCategoryOut[]>({
    queryKey: ["competence-categories-active"],
    queryFn: () => competenceCategoriesApi.list(true),
    staleTime: 300_000,
  });
  if (isError) {
    return <p className="text-xs text-destructive">Nie udało się wczytać kategorii.</p>;
  }
  if (!data) return <p className="text-xs text-muted-foreground">Ładowanie…</p>;
  return (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label="Kategoria kompetencji">
      {data.map((cc) => {
        const active = value.includes(cc.id);
        return (
          <button
            key={cc.id}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(toggleInList(value, cc.id))}
            className={cn(
              "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
              active
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-card text-foreground hover:bg-accent",
            )}
          >
            {cc.name_pl}
          </button>
        );
      })}
    </div>
  );
}
