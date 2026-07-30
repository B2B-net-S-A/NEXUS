"use client";

import { useMemo, useState, type KeyboardEvent } from "react";
import { ChevronDown, ChevronUp, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  AdvancedSearchPopover,
  type AdvancedSearchValue,
} from "@/components/v2/filters/AdvancedSearchPopover";
import { CompetenceCategoryFilter } from "@/components/v2/filters/CompetenceCategoryFilter";
import type {
  CandidateSearchRequest,
  LanguageRequirement,
  LanguageLevel,
  CandidateStatusValue,
  AvailabilityStatusValue,
} from "@/lib/candidate-search-api";
import { cn } from "@/lib/utils";

interface FiltersPanelProps {
  value: CandidateSearchRequest;
  onChange: (next: CandidateSearchRequest) => void;
  /** Optional CC counts from search response facets. */
  ccCounts?: Record<number, number>;
  className?: string;
}

const STATUS_OPTIONS: { value: CandidateStatusValue; label: string }[] = [
  { value: "active", label: "Aktywny" },
  { value: "passive", label: "Pasywny" },
  { value: "blacklisted", label: "Blacklist" },
];

const AVAILABILITY_OPTIONS: { value: AvailabilityStatusValue; label: string }[] = [
  { value: "actively_looking", label: "Aktywnie szuka" },
  { value: "open_to_offers", label: "Otwarty na oferty" },
  { value: "not_looking", label: "Nie szuka" },
  { value: "unknown", label: "Nieznane" },
];

const LANG_LEVELS: LanguageLevel[] = ["A1", "A2", "B1", "B2", "C1", "C2", "native"];

/**
 * Container that exposes all NEXUS structured chip filters in one panel.
 * The boolean buckets (q_all/q_any/q_none) live inside a popover so the panel
 * stays compact; everything else is visible up-front for fast scanning.
 *
 * Pure controlled component — does not fire searches itself; the parent owns
 * `value` and is responsible for triggering the API call (typically debounced
 * after `onChange` fires).
 */
export function FiltersPanel({
  value,
  onChange,
  ccCounts,
  className,
}: FiltersPanelProps) {
  const [skillDraft, setSkillDraft] = useState<{
    must: string;
    any: string;
    none: string;
  }>({ must: "", any: "", none: "" });
  const [tagDraft, setTagDraft] = useState("");
  const [cityDraft, setCityDraft] = useState("");
  const [moreOpen, setMoreOpen] = useState(false);

  const patch = (next: Partial<CandidateSearchRequest>) => {
    onChange({ ...value, ...next });
  };

  const advanced: AdvancedSearchValue = useMemo(
    () => ({
      all: value.q_all ?? [],
      // Prefer the grouped form; fall back to the legacy flat `q_any` (treated
      // as a single OR-group) so older saved searches still render.
      any:
        value.q_any_groups && value.q_any_groups.length > 0
          ? value.q_any_groups
          : value.q_any && value.q_any.length > 0
            ? [value.q_any]
            : [],
      none: value.q_none ?? [],
    }),
    [value.q_all, value.q_any, value.q_any_groups, value.q_none],
  );

  const setAdvanced = (next: AdvancedSearchValue) => {
    // Persist groups under `q_any_groups`; clear the legacy flat field so the
    // two never disagree on the wire.
    patch({ q_all: next.all, q_any: [], q_any_groups: next.any, q_none: next.none });
  };

  const addToList = (
    key: "skills_must" | "skills_any" | "skills_none" | "tags" | "location_cities",
    raw: string,
  ) => {
    const trimmed = raw.trim();
    if (trimmed.length < 2) return;
    const current = (value[key] as string[] | undefined) ?? [];
    if (current.some((x) => x.toLowerCase() === trimmed.toLowerCase())) return;
    patch({ [key]: [...current, trimmed] } as Partial<CandidateSearchRequest>);
  };

  const removeFromList = (
    key: "skills_must" | "skills_any" | "skills_none" | "tags" | "location_cities",
    idx: number,
  ) => {
    const current = (value[key] as string[] | undefined) ?? [];
    patch({
      [key]: current.filter((_, i) => i !== idx),
    } as Partial<CandidateSearchRequest>);
  };

  const toggleMembership = <T extends string>(
    key: keyof CandidateSearchRequest,
    item: T,
    current: T[] | undefined,
  ) => {
    const cur = current ?? [];
    const next = cur.includes(item)
      ? cur.filter((x) => x !== item)
      : [...cur, item];
    patch({ [key]: next } as Partial<CandidateSearchRequest>);
  };

  const onSkillKey =
    (bucket: "must" | "any" | "none") =>
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter" || e.key === ",") {
        e.preventDefault();
        const raw = skillDraft[bucket];
        const key =
          bucket === "must"
            ? "skills_must"
            : bucket === "any"
              ? "skills_any"
              : "skills_none";
        addToList(key, raw);
        setSkillDraft((d) => ({ ...d, [bucket]: "" }));
      }
    };

  const addLanguage = () => {
    const langs = value.languages ?? [];
    if (langs.length >= 10) return;
    patch({ languages: [...langs, { code: "EN", min_level: "B2" }] });
  };

  const updateLanguage = (idx: number, next: Partial<LanguageRequirement>) => {
    const langs = value.languages ?? [];
    patch({
      languages: langs.map((l, i) => (i === idx ? { ...l, ...next } : l)),
    });
  };

  const removeLanguage = (idx: number) => {
    patch({ languages: (value.languages ?? []).filter((_, i) => i !== idx) });
  };

  const clearAll = () => {
    onChange({
      sort: value.sort ?? "relevance",
      page: 1,
      page_size: value.page_size ?? 50,
      exclude_in_job_id: value.exclude_in_job_id ?? null,
    });
  };

  return (
    <div
      className={cn(
        "space-y-4 rounded-lg border bg-card p-4 dark:border-zinc-800",
        className,
      )}
    >
      {/* Free text + boolean popover */}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={value.q ?? ""}
          onChange={(e) => patch({ q: e.target.value || null })}
          placeholder={
            value.search_mode === "hybrid"
              ? "Szukaj semantycznie (BM25 + dense + rerank)…"
              : "Szukaj w CV (full-text)…"
          }
          className="flex-1 min-w-[16rem]"
        />
        <Button
          type="button"
          variant={value.search_mode === "hybrid" ? "primary" : "outline"}
          size="sm"
          onClick={() =>
            patch({
              search_mode:
                value.search_mode === "hybrid" ? "boolean" : "hybrid",
            })
          }
          title={
            value.search_mode === "hybrid"
              ? "Tryb hybrydowy: Postgres FTS + Voyage embeddings + RRF fusion + Voyage Rerank 2.5. Wyższa jakość, dłuższa latencja (~600ms rerank)."
              : "Włącz wyszukiwanie semantyczne (BM25 + dense + rerank)."
          }
        >
          {value.search_mode === "hybrid" ? "Semantycznie ✓" : "Semantycznie"}
        </Button>
        <AdvancedSearchPopover value={advanced} onChange={setAdvanced} />
        <Button variant="ghost" size="sm" onClick={clearAll}>
          Wyczyść
        </Button>
      </div>

      {/* Competence Category — flagship filter */}
      <div className="space-y-2">
        <Label className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
          Kategoria kompetencji
        </Label>
        <CompetenceCategoryFilter
          selected={value.competence_category_ids ?? []}
          onChange={(ids) => patch({ competence_category_ids: ids })}
          mode="multi"
          counts={ccCounts}
        />
      </div>

      {/* Skills — dwa sygnały rankingowe + jedno twarde wykluczenie.
          Etykiety celowo NIE mówią "musi mieć": backend traktuje `skills_must`
          i `skills_any` wyłącznie jako ranking (`skills_soft_rank` scala je
          w JEDEN zbiór `must ∪ any`, patrz structured_candidate_search.py),
          a twardym filtrem jest tylko `skills_none`. Poprzednie etykiety
          obiecywały bramkę shortlisty, której nie ma — i sugerowały różnicę
          siły między dwoma polami, które robią dokładnie to samo. */}
      <div className="grid gap-3 sm:grid-cols-3">
        {(
          [
            ["must", "Skills (preferowane)", "emerald"],
            ["any", "Skills (dodatkowe)", "sky"],
            ["none", "Skills (wyklucz)", "rose"],
          ] as const
        ).map(([bucket, label, tone]) => {
          const key =
            bucket === "must"
              ? "skills_must"
              : bucket === "any"
                ? "skills_any"
                : "skills_none";
          const items = (value[key] as string[] | undefined) ?? [];
          return (
            <div key={bucket} className="space-y-1.5">
              <Label className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
                {label}
              </Label>
              <div className="flex flex-wrap items-center gap-1.5">
                {items.map((s, i) => (
                  <Badge
                    key={`${s}-${i}`}
                    variant="neutral"
                    className={cn(
                      "gap-1",
                      tone === "emerald" &&
                        "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-200",
                      tone === "sky" &&
                        "bg-sky-50 text-sky-700 dark:bg-sky-900/30 dark:text-sky-200",
                      tone === "rose" &&
                        "bg-rose-50 text-rose-700 dark:bg-rose-900/30 dark:text-rose-200",
                    )}
                  >
                    {s}
                    <button
                      type="button"
                      onClick={() => removeFromList(key, i)}
                      aria-label={`Usuń ${s}`}
                      className="hover:opacity-70"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </Badge>
                ))}
                <Input
                  value={skillDraft[bucket]}
                  onChange={(e) =>
                    setSkillDraft((d) => ({ ...d, [bucket]: e.target.value }))
                  }
                  onKeyDown={onSkillKey(bucket)}
                  placeholder="np. Python, React"
                  className="h-8 w-28 text-xs"
                />
              </div>
            </div>
          );
        })}
      </div>
      <p className="-mt-1 text-[11px] leading-snug text-zinc-500 dark:text-zinc-400">
        „Preferowane" i „dodatkowe" <strong className="font-medium">podbijają ranking</strong>,
        ale nikogo nie usuwają z wyników — kandydat bez wpisanej umiejętności nadal
        się pokaże, tylko niżej. Twardo wyklucza wyłącznie pole „wyklucz".
      </p>

      {/* Experience years range */}
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="space-y-1.5">
          <Label className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
            Lata doświadczenia (min – max)
          </Label>
          <div className="flex items-center gap-2">
            <Input
              type="number"
              min={0}
              max={60}
              value={value.experience_years_min ?? ""}
              onChange={(e) =>
                patch({
                  experience_years_min: e.target.value
                    ? Number.parseInt(e.target.value, 10)
                    : null,
                })
              }
              placeholder="min"
              className="w-20 text-sm"
            />
            <span className="text-zinc-400">–</span>
            <Input
              type="number"
              min={0}
              max={60}
              value={value.experience_years_max ?? ""}
              onChange={(e) =>
                patch({
                  experience_years_max: e.target.value
                    ? Number.parseInt(e.target.value, 10)
                    : null,
                })
              }
              placeholder="max"
              className="w-20 text-sm"
            />
          </div>
        </div>

        {/* City picker */}
        <div className="space-y-1.5">
          <Label className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
            Miasto
          </Label>
          <div className="flex flex-wrap items-center gap-1.5">
            {(value.location_cities ?? []).map((c, i) => (
              <Badge key={`${c}-${i}`} variant="neutral" className="gap-1">
                {c}
                <button
                  type="button"
                  onClick={() => removeFromList("location_cities", i)}
                  aria-label={`Usuń ${c}`}
                >
                  <X className="h-3 w-3" />
                </button>
              </Badge>
            ))}
            <Input
              value={cityDraft}
              onChange={(e) => setCityDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === ",") {
                  e.preventDefault();
                  addToList("location_cities", cityDraft);
                  setCityDraft("");
                }
              }}
              placeholder="np. Warszawa"
              className="h-8 w-28 text-xs"
            />
          </div>
        </div>
      </div>

      {/* Status + availability — chip toggles */}
      <div className="flex flex-wrap items-start gap-4">
        <div className="space-y-1.5">
          <Label className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
            Status
          </Label>
          <div className="flex flex-wrap gap-1.5">
            {STATUS_OPTIONS.map((opt) => {
              const active = (value.status ?? []).includes(opt.value);
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() =>
                    toggleMembership("status", opt.value, value.status)
                  }
                  className={cn(
                    "rounded-md border px-2.5 py-1 text-xs",
                    active
                      ? "border-violet-500 bg-violet-50 text-violet-700 dark:bg-violet-900/40 dark:text-violet-200"
                      : "border-zinc-200 bg-white text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300",
                  )}
                >
                  {opt.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
            Dostępność
          </Label>
          <div className="flex flex-wrap gap-1.5">
            {AVAILABILITY_OPTIONS.map((opt) => {
              const active = (value.availability_status ?? []).includes(opt.value);
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() =>
                    toggleMembership(
                      "availability_status",
                      opt.value,
                      value.availability_status,
                    )
                  }
                  className={cn(
                    "rounded-md border px-2.5 py-1 text-xs",
                    active
                      ? "border-violet-500 bg-violet-50 text-violet-700 dark:bg-violet-900/40 dark:text-violet-200"
                      : "border-zinc-200 bg-white text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300",
                  )}
                >
                  {opt.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* "Więcej" — collapsible advanced toggles */}
      <div>
        <button
          type="button"
          onClick={() => setMoreOpen((x) => !x)}
          className="flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
        >
          {moreOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          {moreOpen ? "Mniej filtrów" : "Więcej filtrów"}
        </button>

        {moreOpen && (
          <div className="mt-3 space-y-3 border-t pt-3 dark:border-zinc-800">
            <div className="flex flex-wrap gap-x-6 gap-y-2 text-xs">
              {(
                [
                  ["is_champion", "Champion"],
                  ["is_ambassador", "Ambasador"],
                  ["open_to_side_projects", "Side projects"],
                  ["open_to_sales_support", "Sales support"],
                  ["open_to_expert_consult", "Expert consult"],
                  ["has_cv", "Ma CV"],
                  ["has_linkedin", "Ma LinkedIn"],
                ] as const
              ).map(([key, label]) => {
                const checked = value[key] === true;
                return (
                  <label
                    key={key}
                    className="flex items-center gap-1.5 cursor-pointer select-none"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) =>
                        patch({ [key]: e.target.checked || null } as Partial<CandidateSearchRequest>)
                      }
                      className="h-3.5 w-3.5 rounded border-zinc-300 text-violet-600 focus:ring-violet-500"
                    />
                    <span>{label}</span>
                  </label>
                );
              })}
            </div>

            {/* Languages picker */}
            <div className="space-y-1.5">
              <Label className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
                Języki
              </Label>
              <div className="space-y-1.5">
                {(value.languages ?? []).map((lang, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <Input
                      value={lang.code}
                      onChange={(e) =>
                        updateLanguage(i, { code: e.target.value.toUpperCase() })
                      }
                      maxLength={3}
                      className="h-8 w-16 text-xs uppercase"
                      placeholder="EN"
                    />
                    <select
                      value={lang.min_level}
                      onChange={(e) =>
                        updateLanguage(i, {
                          min_level: e.target.value as LanguageLevel,
                        })
                      }
                      className="h-8 rounded-md border border-zinc-200 bg-white px-2 text-xs dark:border-zinc-700 dark:bg-zinc-900"
                    >
                      {LANG_LEVELS.map((lvl) => (
                        <option key={lvl} value={lvl}>
                          ≥ {lvl}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => removeLanguage(i)}
                      className="text-zinc-400 hover:text-rose-600"
                      aria-label="Usuń język"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ))}
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 text-xs"
                  onClick={addLanguage}
                  disabled={(value.languages ?? []).length >= 10}
                >
                  + Dodaj język
                </Button>
              </div>
            </div>

            {/* Tags picker */}
            <div className="space-y-1.5">
              <Label className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
                Tagi
              </Label>
              <div className="flex flex-wrap items-center gap-1.5">
                {(value.tags ?? []).map((t, i) => (
                  <Badge key={`${t}-${i}`} variant="neutral" className="gap-1">
                    {t}
                    <button
                      type="button"
                      onClick={() => removeFromList("tags", i)}
                      aria-label={`Usuń ${t}`}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </Badge>
                ))}
                <Input
                  value={tagDraft}
                  onChange={(e) => setTagDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === ",") {
                      e.preventDefault();
                      addToList("tags", tagDraft);
                      setTagDraft("");
                    }
                  }}
                  placeholder="tag,..."
                  className="h-8 w-28 text-xs"
                />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
