"use client";

import { useEffect, useRef, useState } from "react";
import { X, Plus, Filter, Globe, Home, Building2 } from "lucide-react";
import { skillsApi, type SkillSuggestion } from "@/lib/api";
import { cn } from "@/lib/utils";

export interface AdvancedFilters {
  skills: string[];
  skillCombine: "and" | "or";
  remotePolicy: "" | "remote" | "hybrid" | "onsite";
  minSalary: number | null;
  maxSalary: number | null;
}

export const EMPTY_ADVANCED_FILTERS: AdvancedFilters = {
  skills: [],
  skillCombine: "and",
  remotePolicy: "",
  minSalary: null,
  maxSalary: null,
};

interface AdvancedFilterBarProps {
  value: AdvancedFilters;
  onChange: (next: AdvancedFilters) => void;
}

const REMOTE_OPTIONS: Array<{
  value: AdvancedFilters["remotePolicy"];
  label: string;
  icon: typeof Globe;
}> = [
  { value: "", label: "Dowolnie", icon: Filter },
  { value: "remote", label: "Zdalna", icon: Globe },
  { value: "hybrid", label: "Hybryda", icon: Home },
  { value: "onsite", label: "Stacjonarna", icon: Building2 },
];

export function AdvancedFilterBar({ value, onChange }: AdvancedFilterBarProps) {
  const [input, setInput] = useState("");
  const [suggestions, setSuggestions] = useState<SkillSuggestion[]>([]);
  const [loadingSuggest, setLoadingSuggest] = useState(false);
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  // Fetch autocomplete on typing (debounced)
  useEffect(() => {
    let cancelled = false;
    const q = input.trim();
    if (q.length < 2) {
      setSuggestions([]);
      return;
    }
    setLoadingSuggest(true);
    const handle = setTimeout(async () => {
      try {
        const res = await skillsApi.autocomplete(q, 10);
        if (!cancelled) setSuggestions(res.data.items);
      } catch {
        if (!cancelled) setSuggestions([]);
      } finally {
        if (!cancelled) setLoadingSuggest(false);
      }
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [input]);

  // Close dropdown on outside click
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (!wrapperRef.current) return;
      if (!wrapperRef.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, []);

  const addSkill = (name: string) => {
    const clean = name.trim().toLowerCase();
    if (!clean) return;
    if (value.skills.some((s) => s.toLowerCase() === clean)) return;
    onChange({ ...value, skills: [...value.skills, clean] });
    setInput("");
    setSuggestions([]);
  };

  const removeSkill = (name: string) => {
    onChange({ ...value, skills: value.skills.filter((s) => s !== name) });
  };

  const toggleCombine = () => {
    onChange({ ...value, skillCombine: value.skillCombine === "and" ? "or" : "and" });
  };

  return (
    <div className="space-y-2" ref={wrapperRef}>
      {/* Skills input with autocomplete */}
      <div className="relative">
        <div className="flex items-center gap-1.5 flex-wrap px-2 py-1.5 border border-border dark:border-border rounded-lg bg-card dark:bg-muted min-h-[34px]">
          {value.skills.map((skill, idx) => (
            <span
              key={skill}
              className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded-md bg-primary/15 text-primary border border-primary/20 font-medium"
            >
              {idx > 0 && (
                <button
                  type="button"
                  onClick={toggleCombine}
                  className="text-[9px] uppercase tracking-wide font-bold px-0.5 mr-0.5 rounded bg-primary/20 hover:bg-primary/25"
                  title="Zmień AND/OR między chipami"
                >
                  {value.skillCombine}
                </button>
              )}
              {skill}
              <button
                type="button"
                onClick={() => removeSkill(skill)}
                className="ml-0.5 hover:text-primary"
                aria-label={`Usuń ${skill}`}
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
          <input
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                if (suggestions.length > 0) addSkill(suggestions[0].name);
                else if (input.trim()) addSkill(input);
              } else if (e.key === "Backspace" && !input && value.skills.length > 0) {
                removeSkill(value.skills[value.skills.length - 1]);
              }
            }}
            placeholder={value.skills.length === 0 ? "Umiejętności (np. Python, AWS)…" : ""}
            className="flex-1 min-w-[120px] text-xs bg-transparent focus:outline-none dark:text-foreground"
          />
        </div>

        {open && suggestions.length > 0 && (
          <div className="absolute left-0 right-0 top-full mt-1 z-20 max-h-56 overflow-y-auto bg-card dark:bg-muted border border-border dark:border-border rounded-lg shadow-lg">
            {loadingSuggest && (
              <div className="px-3 py-1.5 text-[11px] text-muted-foreground">Szukam…</div>
            )}
            {suggestions.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => addSkill(s.name)}
                className="w-full text-left px-3 py-1.5 text-xs hover:bg-primary/10 dark:hover:bg-primary/30 flex items-center justify-between"
              >
                <span className="capitalize">{s.name}</span>
                {s.category && (
                  <span className="text-[9px] text-muted-foreground uppercase tracking-wide">
                    {s.category}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Row: remote + salary */}
      <div className="flex gap-2 flex-wrap">
        <div className="flex gap-1 border border-border dark:border-border rounded-lg p-0.5 bg-card dark:bg-muted">
          {REMOTE_OPTIONS.map((opt) => {
            const Icon = opt.icon;
            const active = value.remotePolicy === opt.value;
            return (
              <button
                key={opt.value || "any"}
                type="button"
                onClick={() => onChange({ ...value, remotePolicy: opt.value })}
                className={cn(
                  "inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md transition-colors",
                  active
                    ? "bg-primary text-white"
                    : "text-muted-foreground dark:text-muted-foreground hover:bg-muted dark:hover:bg-gray-600"
                )}
                title={opt.label}
              >
                <Icon className="w-3 h-3" aria-hidden />
                {opt.label}
              </button>
            );
          })}
        </div>
        <input
          type="number"
          value={value.minSalary ?? ""}
          min={0}
          step={1000}
          onChange={(e) =>
            onChange({
              ...value,
              minSalary: e.target.value === "" ? null : Number(e.target.value),
            })
          }
          placeholder="od PLN"
          className="w-24 px-2 py-1 text-xs border border-border dark:border-border rounded-lg focus:outline-none focus:ring-2 focus-visible:ring-ring bg-card dark:bg-muted dark:text-foreground"
        />
        <input
          type="number"
          value={value.maxSalary ?? ""}
          min={0}
          step={1000}
          onChange={(e) =>
            onChange({
              ...value,
              maxSalary: e.target.value === "" ? null : Number(e.target.value),
            })
          }
          placeholder="do PLN"
          className="w-24 px-2 py-1 text-xs border border-border dark:border-border rounded-lg focus:outline-none focus:ring-2 focus-visible:ring-ring bg-card dark:bg-muted dark:text-foreground"
        />
      </div>
    </div>
  );
}
