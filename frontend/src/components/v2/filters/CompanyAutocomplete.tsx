"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import api from "@/lib/api";
import { Input } from "@/components/ui/input";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";

interface CompanySuggestion {
  name: string;
  count: number;
}

interface CompanyAutocompleteProps {
  value: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  suggestEndpoint?: string;
  limit?: number;
}

export function CompanyAutocomplete({
  value,
  onChange,
  placeholder,
  suggestEndpoint,
  limit = 20,
}: CompanyAutocompleteProps) {
  const [input, setInput] = useState("");
  const [focused, setFocused] = useState(false);
  const debounced = useDebouncedValue(input, 200);

  const { data } = useQuery<CompanySuggestion[]>({
    queryKey: ["company-suggest", suggestEndpoint ?? "", debounced, limit],
    queryFn: () =>
      api
        .get(suggestEndpoint!, { params: { q: debounced, limit } })
        .then((r) => r.data),
    enabled: Boolean(suggestEndpoint) && focused,
    staleTime: 30_000,
  });

  const lowered = new Set(value.map((v) => v.toLowerCase()));
  const suggestions = (data ?? []).filter(
    (s) => !lowered.has(s.name.toLowerCase())
  );

  const addTag = (raw: string) => {
    const trimmed = raw.trim();
    if (!trimmed) return;
    if (lowered.has(trimmed.toLowerCase())) {
      setInput("");
      return;
    }
    onChange([...value, trimmed]);
    setInput("");
  };

  const removeTag = (name: string) => {
    onChange(value.filter((v) => v !== name));
  };

  const showDropdown =
    Boolean(suggestEndpoint) && focused && suggestions.length > 0;

  return (
    <div className="relative">
      {value.length > 0 && (
        <div className="flex gap-1.5 flex-wrap mb-2">
          {value.map((name) => (
            <span
              key={name}
              className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-[hsl(var(--accent-soft))] text-[hsl(var(--accent))]"
            >
              <span className="truncate max-w-[180px]">{name}</span>
              <button
                type="button"
                onClick={() => removeTag(name)}
                className="hover:opacity-70"
                aria-label={`Usuń ${name}`}
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}
      <Input
        placeholder={placeholder}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => {
          setTimeout(() => setFocused(false), 150);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            addTag(input);
          }
        }}
      />
      {showDropdown && (
        <div
          className={cn(
            "absolute z-50 mt-1 w-full max-h-60 overflow-auto",
            "rounded-v2-s border border-[hsl(var(--border-subtle))]",
            "bg-[hsl(var(--bg-surface))] shadow-lg"
          )}
        >
          {suggestions.map((s) => (
            <button
              key={s.name}
              type="button"
              className={cn(
                "w-full flex items-center justify-between px-2.5 py-1.5",
                "text-xs text-left",
                "hover:bg-[hsl(var(--bg-hover))]"
              )}
              onMouseDown={(e) => {
                e.preventDefault();
                addTag(s.name);
              }}
            >
              <span className="truncate flex-1">{s.name}</span>
              <span className="ml-2 text-[hsl(var(--text-muted))] flex-shrink-0">
                {s.count}
              </span>
            </button>
          ))}
        </div>
      )}
      <p className="text-[10px] text-[hsl(var(--text-muted))] mt-1">
        Enter, aby dodać.
        {value.length > 1 && " Wszystkie wartości OR."}
      </p>
    </div>
  );
}
