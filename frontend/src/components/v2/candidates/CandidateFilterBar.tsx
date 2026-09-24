"use client";

import { useId, useState, type ReactNode } from "react";
import {
  CalendarClock,
  ChevronDown,
  History,
  Home,
  MapPin,
  Plus,
  SlidersHorizontal,
  Sparkles,
  Wallet,
  X,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
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
  AVAILABILITY_CHOICES,
  availabilityChoiceFor,
} from "@/lib/candidate-availability-choice";
import {
  CANDIDATE_STATUS_OPTIONS,
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
import {
  filterGroupCounts,
  locationSummary,
  rateSummary,
  remoteSummary,
} from "@/lib/candidate-filter-groups";
import { PillGroup, toggleInList } from "@/components/v2/candidates/filters/FilterPillGroup";
import { SkillBucketsField } from "@/components/v2/candidates/SkillBucketsField";
import { HideUnknownToggle } from "@/components/v2/candidates/UnknownFieldBadges";
import {
  ContactFields,
  KeywordFields,
  LocationFields,
} from "@/components/v2/candidates/CandidateSearchFields";
import { TalentPoolMultiSelect } from "@/components/v2/filters/TalentPoolMultiSelect";
import { AddedByMultiSelect } from "@/components/v2/filters/AddedByMultiSelect";
import { CompanyAutocomplete } from "@/components/v2/filters/CompanyAutocomplete";
import { TAG_SUGGEST_ENDPOINT } from "@/lib/api/candidateTags";
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

export interface CandidateFilterBarProps {
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

function FieldLabel({ children, htmlFor }: { children: ReactNode; htmlFor?: string }) {
  return (
    <label htmlFor={htmlFor} className="block text-xs text-muted-foreground">
      {children}
    </label>
  );
}

/**
 * Zwijana grupa w szufladzie „Więcej filtrów”. Domyślnie zamknięta, chyba że coś w niej jest
 * ustawione — aktywny filtr nie może się chować (wyglądałoby, że działa
 * filtr, którego nie widać).
 */
function RailGroup({
  title,
  activeCount,
  children,
}: {
  title: string;
  activeCount: number;
  children: ReactNode;
}) {
  const [manual, setManual] = useState<boolean | null>(null);
  const open = manual ?? activeCount > 0;
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
  unit,
  min,
  max,
  onChange,
  parse,
  maxValue,
}: {
  label: string;
  unit: string;
  min: number | null;
  max: number | null;
  onChange: (next: { min: number | null; max: number | null }) => void;
  parse: (raw: string | null) => number | null;
  maxValue?: number;
}) {
  return (
    <div className="space-y-1">
      <FieldLabel>{label}</FieldLabel>
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
 * Przycisk filtra na pasku: otwiera okienko z polami grupy. Ustawiony filtr
 * jest wyróżniony i niesie swoją wartość (albo licznik), a ✕ obok czyści
 * grupę — ukryty, ale ustawiony filtr nie może wyglądać, jakby go nie było.
 */
function FilterPill({
  label,
  icon,
  summary,
  count,
  onClear,
  contentClassName,
  children,
}: {
  label: string;
  icon: ReactNode;
  /** Wartość na przycisku („do 160 zł/h”); bez niej przycisk pokazuje licznik. */
  summary?: string | null;
  count: number;
  onClear?: () => void;
  contentClassName?: string;
  children: ReactNode;
}) {
  const active = count > 0;
  return (
    <div
      className={cn(
        "inline-flex h-8 shrink-0 items-center rounded-full border text-xs font-medium transition-colors",
        active
          ? "border-primary/30 bg-primary/10 text-primary"
          : "border-border bg-card text-foreground hover:bg-accent",
      )}
    >
      <Popover>
        <PopoverTrigger asChild>
          <button
            type="button"
            className={cn(
              "flex h-full items-center gap-1.5 rounded-full pl-3 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
              active && onClear ? "pr-1" : "pr-2.5",
            )}
          >
            <span aria-hidden className="[&>svg]:h-3.5 [&>svg]:w-3.5">
              {icon}
            </span>
            <span className="flex min-w-0 items-baseline">
              {label}
              {active && summary && (
                <span className="max-w-[200px] truncate font-semibold">: {summary}</span>
              )}
            </span>
            {active && !summary ? (
              <span className="rounded-full bg-primary px-1.5 text-[10px] leading-4 text-primary-foreground">
                {count}
              </span>
            ) : null}
            <ChevronDown className="h-3.5 w-3.5 opacity-60" aria-hidden />
          </button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          className={cn("w-80 space-y-3 text-sm", contentClassName)}
        >
          {children}
        </PopoverContent>
      </Popover>
      {active && onClear && (
        <button
          type="button"
          onClick={onClear}
          aria-label={`Wyczyść: ${label}`}
          className="mr-1 flex h-6 w-6 items-center justify-center rounded-full hover:bg-primary/15 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
        >
          <X className="h-3 w-3" aria-hidden />
        </button>
      )}
    </div>
  );
}

/**
 * Filtry listy kandydatów nad tabelą (wariant A, decyzja Artura 23.09.2026).
 * Pas słów kluczowych jak w Traffit (wszystkie / którekolwiek / żadne +
 * „Szukaj w”), pod nim rząd przycisków: stawka, lokalizacja, tryb pracy
 * (to, czym zespół szuka najczęściej — decyzja 22.09), potem historia z nami,
 * umiejętności, dostępność i „Więcej filtrów” (szuflada z resztą: profil,
 * firma, źródło, „Inne”). Tabela dostaje całą szerokość ekranu.
 */
export function CandidateFilterBar({
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
}: CandidateFilterBarProps) {
  const [moreOpen, setMoreOpen] = useState(false);
  // Na telefonie pas słów kluczowych zajmowałby pół ekranu — chowa się za
  // przyciskiem; od `md` stoi zawsze. Ustawione słowa otwierają go od razu.
  const keywordCount =
    filters.qAll.length + (filters.qAny[0]?.length ?? 0) + filters.qNone.length;
  const [keywordsOpen, setKeywordsOpen] = useState(keywordCount > 0);
  const keywordsId = useId();
  const mine =
    currentUserId !== null &&
    filters.addedByIds.length === 1 &&
    filters.addedByIds[0] === currentUserId;
  const everyone = filters.addedByIds.length === 0;
  const counts = filterGroupCounts(filters, stage, skills);

  const aboutCount =
    (filters.experienceMin !== null || filters.experienceMax !== null ? 1 : 0) +
    filters.languages.length +
    filters.competenceCategoryIds.length;
  const companyCount =
    filters.currentCompany.length +
    filters.pastCompany.length +
    filters.currentTitle.length +
    (filters.recentlyChangedJobs ? 1 : 0);
  const sourceCount = filters.poolIds.length + filters.addedByIds.length;
  const otherCount =
    filters.tags.length +
    filters.status.length +
    filters.openTo.length +
    (filters.hideUnknown ? 1 : 0) +
    filters.qAny.slice(1).flat().length;

  return (
    <section aria-label="Filtry kandydatów" className={cn("space-y-2 text-sm", className)} data-help="candidates.list.filters">
      <button
        type="button"
        aria-expanded={keywordsOpen}
        aria-controls={keywordsId}
        onClick={() => setKeywordsOpen(!keywordsOpen)}
        className="flex w-full items-center justify-between rounded-lg border border-border bg-card px-3 py-2 text-xs font-medium text-foreground md:hidden"
      >
        <span>
          Słowa kluczowe{keywordCount > 0 ? ` (${keywordCount})` : ""}
        </span>
        <ChevronDown
          className={cn("h-3.5 w-3.5 opacity-60 transition-transform", keywordsOpen && "rotate-180")}
          aria-hidden
        />
      </button>
      <KeywordFields
        id={keywordsId}
        filters={filters}
        onPatch={onPatch}
        className={keywordsOpen ? undefined : "max-md:hidden"}
      />

      <div className="-mx-1 flex items-center gap-2 overflow-x-auto px-1 pb-1 md:flex-wrap md:overflow-visible md:pb-0">
        <FilterPill
          label="Stawka"
          icon={<Wallet />}
          summary={rateSummary(filters)}
          count={counts.rate}
          onClear={() => onPatch({ rateMin: null, rateMax: null })}
          contentClassName="w-72"
        >
          <RangeInputs
            label="Stawka B2B"
            unit="zł/h"
            min={filters.rateMin}
            max={filters.rateMax}
            parse={parseRateBound}
            onChange={({ min, max }) => onPatch({ rateMin: min, rateMax: max })}
          />
        </FilterPill>
        <FilterPill
          label="Lokalizacja"
          icon={<MapPin />}
          summary={locationSummary(filters)}
          count={counts.location}
          onClear={() => onPatch({ location: "", locationRadiusKm: null, voivodeships: [] })}
        >
          <LocationFields filters={filters} onPatch={onPatch} />
        </FilterPill>
        <FilterPill
          label="Tryb pracy"
          icon={<Home />}
          summary={remoteSummary(filters)}
          count={counts.remote}
          onClear={() => onPatch({ remote: [] })}
          contentClassName="w-auto"
        >
          <PillGroup
            label="Tryb pracy"
            options={REMOTE_OPTIONS}
            value={filters.remote}
            onToggle={(v) => onPatch({ remote: toggleInList(filters.remote, v) })}
          />
        </FilterPill>

        <span aria-hidden className="mx-0.5 h-5 w-px shrink-0 bg-border" />

        <FilterPill
          label="Historia z nami"
          icon={<History />}
          count={counts.history}
          onClear={() => {
            onPatch({
              recruitmentIds: [],
              recruitmentMatch: "assigned",
              sentToClientFrom: "",
              sentToClientTo: "",
              workedAtClientIds: [],
              contacted: null,
              contactedFrom: "",
              contactedTo: "",
              contactedByIds: [],
            });
            onStageChange({
              stages: [],
              currentOnly: false,
              clientIds: [],
              movedByIds: [],
              movedAfter: "",
              movedBefore: "",
            });
          }}
          contentClassName="max-h-[70vh] w-[420px] max-w-[calc(100vw-2rem)] overflow-y-auto"
        >
          <HistoryFields
            filters={filters}
            onPatch={onPatch}
            stage={stage}
            onStageChange={onStageChange}
          />
        </FilterPill>
        <FilterPill
          label="Umiejętności"
          icon={<Sparkles />}
          count={counts.skills}
          onClear={() => onSkillsChange({ required: [], preferred: [], excluded: [] })}
          contentClassName="w-[360px] max-w-[calc(100vw-2rem)]"
        >
          <SkillBucketsField value={skills} onChange={onSkillsChange} compact />
        </FilterPill>
        <FilterPill
          label="Dostępność"
          icon={<CalendarClock />}
          count={counts.availability}
          onClear={() => onPatch({ availability: [], employment: [] })}
        >
          <AvailabilityChoiceField filters={filters} onPatch={onPatch} />
        </FilterPill>

        <button
          type="button"
          onClick={() => setMoreOpen(true)}
          data-help="candidates.list.more"
          className={cn(
            "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
            counts.more > 0
              ? "border-primary/30 bg-primary/10 text-primary"
              : "border-border bg-card text-foreground hover:bg-accent",
          )}
        >
          <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden />
          Więcej filtrów
          {counts.more > 0 && (
            <span className="rounded-full bg-primary px-1.5 text-[10px] leading-4 text-primary-foreground">
              {counts.more}
            </span>
          )}
        </button>
        {activeCount > 0 && (
          <button
            type="button"
            onClick={onClearAll}
            className="shrink-0 px-1 text-xs font-medium text-primary hover:underline"
          >
            Wyczyść ({activeCount})
          </button>
        )}
      </div>

      <Sheet open={moreOpen} onOpenChange={setMoreOpen}>
        <SheetContent side="right" size="sm">
          <SheetHeader>
            <SheetTitle>Więcej filtrów</SheetTitle>
            <SheetDescription>Wyniki aktualizują się na bieżąco.</SheetDescription>
          </SheetHeader>
          <SheetBody>
            <div className="text-sm" data-testid="candidate-more-filters">
              <RailGroup title="Doświadczenie, języki, kategoria" activeCount={aboutCount}>
                <RangeInputs
                  label="Lata doświadczenia"
                  unit="lat"
                  min={filters.experienceMin}
                  max={filters.experienceMax}
                  maxValue={60}
                  parse={parseYearBound}
                  onChange={({ min, max }) => onPatch({ experienceMin: min, experienceMax: max })}
                />
                <div className="space-y-1">
                  <FieldLabel>Języki</FieldLabel>
                  <LanguageFilterField
                    value={filters.languages}
                    onChange={(next) => onPatch({ languages: next })}
                  />
                </div>
                <div className="space-y-1">
                  <FieldLabel>Kategoria kompetencji</FieldLabel>
                  <CompetenceCategoryPills
                    value={filters.competenceCategoryIds}
                    onChange={(ids) => onPatch({ competenceCategoryIds: ids })}
                  />
                </div>
              </RailGroup>
              <RailGroup title="Firma i stanowisko" activeCount={companyCount}>
                <CompanyFields filters={filters} onPatch={onPatch} />
              </RailGroup>
              <RailGroup title="Kto dodał, pule" activeCount={sourceCount}>
                <div className="space-y-1">
                  <FieldLabel>Kogo pokazać</FieldLabel>
                  <div
                    role="radiogroup"
                    aria-label="Kogo pokazać"
                    className="grid grid-cols-2 gap-1 rounded-lg bg-muted p-1"
                  >
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
                <div className="space-y-1">
                  <FieldLabel>Dodany przez</FieldLabel>
                  <AddedByMultiSelect value={filters.addedByIds} onChange={(v) => onPatch({ addedByIds: v })} />
                </div>
                <div className="space-y-1">
                  <FieldLabel>Pula talentów</FieldLabel>
                  <TalentPoolMultiSelect value={filters.poolIds} onChange={(v) => onPatch({ poolIds: v })} />
                </div>
              </RailGroup>
              <RailGroup title="Inne" activeCount={otherCount}>
                <div className="space-y-1">
                  <FieldLabel>Tagi</FieldLabel>
                  <CompanyAutocomplete
                    value={filters.tags}
                    onChange={(v) => onPatch({ tags: v })}
                    placeholder="np. senior, bankowość"
                    suggestEndpoint={TAG_SUGGEST_ENDPOINT}
                  />
                  <p className="text-[11px] text-muted-foreground">
                    Cały tag, bez wielkości liter — kandydat musi mieć każdy wybrany.
                  </p>
                </div>
                <div className="space-y-1">
                  <FieldLabel>Kolejne grupy „którekolwiek” (LUB)</FieldLabel>
                  <p className="text-[11px] text-muted-foreground">
                    Każda grupa musi mieć co najmniej jedno trafienie, np. (React lub Vue) i (Java lub Kotlin).
                    Pierwsza grupa to pole „Zawiera którekolwiek” nad tabelą.
                  </p>
                  <AdvancedSearchPopover
                    value={{ ...phrases, any: phrases.any.slice(1) }}
                    hideHeader
                    sections={["any"]}
                    onChange={(next) => onPatch({ qAny: [filters.qAny[0] ?? [], ...next.any] })}
                  />
                </div>
                <CompactPills
                  label="Status w bazie"
                  options={CANDIDATE_STATUS_OPTIONS}
                  value={filters.status}
                  onToggle={(v) => onPatch({ status: toggleInList(filters.status, v) })}
                />
                <CompactPills
                  label="Otwarty na dodatkowe"
                  options={OPEN_TO_OPTIONS}
                  value={filters.openTo}
                  onToggle={(v) => onPatch({ openTo: toggleInList(filters.openTo, v) })}
                />
                <div className="space-y-1">
                  <HideUnknownToggle
                    checked={filters.hideUnknown}
                    onChange={(next) => onPatch({ hideUnknown: next })}
                  />
                  <p className="text-[11px] text-muted-foreground">
                    Bez zaznaczenia osoby bez miasta, stażu albo stawki zostają na liście.
                  </p>
                </div>
              </RailGroup>
            </div>
          </SheetBody>
          <SheetFooter>
            <Button variant="primary" onClick={() => setMoreOpen(false)}>
              {resultLabel ? `Pokaż ${resultLabel}` : "Gotowe"}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </section>
  );
}

function HistoryFields({
  filters,
  onPatch,
  stage,
  onStageChange,
}: {
  filters: CandidateFilters;
  onPatch: (patch: Partial<CandidateFilters>) => void;
  stage: StageFilterValue;
  onStageChange: (patch: Partial<StageFilterValue>) => void;
}) {
  return (
    <div className="space-y-3">
      <p className="text-[11px] text-muted-foreground">
        Poprzednie rekrutacje, etapy i klienci, u których kandydat był.
      </p>
      <div className="space-y-1">
        <FieldLabel>Brał udział w rekrutacji</FieldLabel>
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
      <ContactFields filters={filters} onPatch={onPatch} />
    </div>
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

/**
 * „Czy można go teraz zaproponować?" — jedna odpowiedź zamiast trzech grup
 * (Dostępność, Zatrudnienie, Status). Ustawienie spoza pytania (stary link,
 * zapisane wyszukiwanie) nie zaznacza żadnej odpowiedzi i mówi o tym wprost.
 */
function AvailabilityChoiceField({
  filters,
  onPatch,
}: {
  filters: CandidateFilters;
  onPatch: (patch: Partial<CandidateFilters>) => void;
}) {
  const current = availabilityChoiceFor(filters);
  const labelId = useId();
  return (
    <div className="space-y-1.5">
      <p id={labelId} className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        Czy można go teraz zaproponować?
      </p>
      <div role="radiogroup" aria-labelledby={labelId} className="space-y-0.5">
        {AVAILABILITY_CHOICES.map((choice) => {
          const checked = current === choice.id;
          return (
            <button
              key={choice.id}
              type="button"
              role="radio"
              aria-checked={checked}
              onClick={() => onPatch({ ...choice.patch })}
              className={cn(
                "flex w-full items-start gap-2 rounded-md border px-2 py-1.5 text-left text-xs transition-colors",
                "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
                checked
                  ? "border-primary bg-primary/10 text-foreground"
                  : "border-transparent text-foreground hover:bg-accent",
              )}
            >
              <span
                aria-hidden
                className={cn(
                  "mt-0.5 flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border-2",
                  checked ? "border-primary" : "border-muted-foreground/40",
                )}
              >
                {checked && <span className="h-1.5 w-1.5 rounded-full bg-primary" />}
              </span>
              <span className="min-w-0">
                <span className="block font-medium">{choice.label}</span>
                {choice.hint && (
                  <span className="block text-[11px] text-muted-foreground">{choice.hint}</span>
                )}
              </span>
            </button>
          );
        })}
      </div>
      {current === null && (
        <p className="text-[11px] text-muted-foreground">
          Ustawione własne połączenie (np. z zapisanego wyszukiwania). Wybierz odpowiedź, żeby je zastąpić.
        </p>
      )}
    </div>
  );
}
