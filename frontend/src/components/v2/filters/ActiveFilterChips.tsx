"use client";

import { X } from "lucide-react";
import type { CandidateFilters } from "@/lib/url-filters";

interface NamedLookup {
  id: number;
  name: string;
}

interface ActiveFilterChipsProps {
  filters: CandidateFilters;
  onUpdate: (next: Partial<CandidateFilters>) => void;
  poolsById?: Map<number, string>;
  usersById?: Map<number, string>;
}

const REMOTE_LABELS: Record<string, string> = {
  remote: "Zdalnie",
  hybrid: "Hybryda",
  onsite: "Stacjonarnie",
};

interface Chip {
  key: string;
  label: string;
  clear: () => void;
}

function collectChips(
  filters: CandidateFilters,
  onUpdate: (next: Partial<CandidateFilters>) => void,
  poolsById?: Map<number, string>,
  usersById?: Map<number, string>
): Chip[] {
  const chips: Chip[] = [];

  if (filters.q) {
    chips.push({
      key: "q",
      label: `„${filters.q}"`,
      clear: () => onUpdate({ q: "", page: 1 }),
    });
  }
  if (filters.status) {
    chips.push({
      key: "status",
      label: `Status: ${filters.status}`,
      clear: () => onUpdate({ status: "", page: 1 }),
    });
  }
  if (filters.location) {
    chips.push({
      key: "loc",
      label: `📍 ${filters.location}`,
      clear: () => onUpdate({ location: "", page: 1 }),
    });
  }
  filters.remote.forEach((mode) => {
    chips.push({
      key: `remote:${mode}`,
      label: REMOTE_LABELS[mode] ?? mode,
      clear: () =>
        onUpdate({
          remote: filters.remote.filter((m) => m !== mode),
          page: 1,
        }),
    });
  });
  filters.skills.forEach((skill) => {
    chips.push({
      key: `skill:${skill}`,
      label: skill,
      clear: () =>
        onUpdate({
          skills: filters.skills.filter((s) => s !== skill),
          page: 1,
        }),
    });
  });
  filters.poolIds.forEach((id) => {
    const name = poolsById?.get(id) ?? `Pula #${id}`;
    chips.push({
      key: `pool:${id}`,
      label: `Pula: ${name}`,
      clear: () =>
        onUpdate({
          poolIds: filters.poolIds.filter((x) => x !== id),
          page: 1,
        }),
    });
  });
  filters.addedByIds.forEach((id) => {
    const name =
      id === 0
        ? "Import systemowy"
        : (usersById?.get(id) ?? `Użytkownik #${id}`);
    chips.push({
      key: `added_by:${id}`,
      label: `Dodał: ${name}`,
      clear: () =>
        onUpdate({
          addedByIds: filters.addedByIds.filter((x) => x !== id),
          page: 1,
        }),
    });
  });
  return chips;
}

export function ActiveFilterChips({
  filters,
  onUpdate,
  poolsById,
  usersById,
}: ActiveFilterChipsProps) {
  const chips = collectChips(filters, onUpdate, poolsById, usersById);
  if (chips.length === 0) return null;

  const clearAll = () =>
    onUpdate({
      q: "",
      status: "",
      location: "",
      remote: [],
      skills: [],
      poolIds: [],
      addedByIds: [],
      page: 1,
    });

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {chips.map((chip) => (
        <button
          key={chip.key}
          onClick={chip.clear}
          className="group inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full bg-[hsl(var(--accent-soft))] text-[hsl(var(--accent))] hover:bg-[hsl(var(--accent))] hover:text-white transition-colors"
          aria-label={`Usuń filtr: ${chip.label}`}
        >
          <span className="truncate max-w-[180px]">{chip.label}</span>
          <X className="h-3 w-3 opacity-70 group-hover:opacity-100" />
        </button>
      ))}
      <button
        onClick={clearAll}
        className="text-xs text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent))] ml-1"
      >
        Wyczyść wszystko
      </button>
    </div>
  );
}
