"use client";

import { useEffect, useId, useState } from "react";
import { X } from "lucide-react";

import { Input } from "@/components/ui/input";

export interface PickedToken {
  /** `null` = nazwa wpisana tekstem (spoza słownika). */
  id: number | null;
  name: string;
}

interface TokenPickerProps {
  label: string;
  value: PickedToken[];
  onChange: (next: PickedToken[]) => void;
  search: (q: string) => Promise<{ id: number; name: string }[]>;
  placeholder?: string;
  /** Podpis przy nazwie spoza słownika (np. „do przejrzenia”). */
  freeTextHint?: string;
}

/** Wybór ze słownika z wyszukiwaniem; Enter dodaje wpisaną nazwę. */
export function TokenPicker({
  label,
  value,
  onChange,
  search,
  placeholder,
  freeTextHint = "spoza słownika",
}: TokenPickerProps) {
  const inputId = useId();
  const listId = useId();
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<{ id: number; name: string }[]>([]);
  const [searchError, setSearchError] = useState(false);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setOptions([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      search(q)
        .then((items) => {
          if (!cancelled) {
            setOptions(items);
            setSearchError(false);
          }
        })
        .catch(() => {
          if (!cancelled) setSearchError(true);
        });
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, search]);

  const has = (token: PickedToken) =>
    value.some((item) =>
      token.id != null ? item.id === token.id : item.name.toLowerCase() === token.name.toLowerCase(),
    );

  const add = (token: PickedToken) => {
    if (!token.name.trim() || has(token)) return;
    onChange([...value, token]);
    setQuery("");
    setOptions([]);
  };

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={inputId} className="text-sm font-medium text-foreground">
        {label}
      </label>
      {value.length ? (
        <ul className="flex flex-wrap gap-1.5" aria-label={`Wybrane: ${label}`}>
          {value.map((token) => (
            <li
              key={`${token.id ?? "t"}-${token.name}`}
              className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/40 px-2 py-0.5 text-xs text-foreground"
            >
              {token.name}
              {token.id == null ? (
                <span className="text-muted-foreground">· {freeTextHint}</span>
              ) : null}
              <button
                type="button"
                aria-label={`Usuń ${token.name}`}
                className="rounded p-0.5 text-muted-foreground hover:text-foreground"
                onClick={() => onChange(value.filter((item) => item !== token))}
              >
                <X className="h-3 w-3" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <Input
        id={inputId}
        value={query}
        placeholder={placeholder}
        aria-controls={listId}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            const exact = options.find(
              (option) => option.name.toLowerCase() === query.trim().toLowerCase(),
            );
            add(exact ? exact : { id: null, name: query.trim() });
          }
        }}
      />
      {options.length ? (
        <ul id={listId} className="max-h-40 overflow-y-auto rounded-md border border-border bg-card text-sm">
          {options.map((option) => (
            <li key={option.id}>
              <button
                type="button"
                className="w-full px-3 py-1.5 text-left hover:bg-muted"
                onClick={() => add(option)}
              >
                {option.name}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {searchError ? (
        <p className="text-xs text-destructive">Nie udało się wyszukać — wpisz nazwę i naciśnij Enter.</p>
      ) : null}
    </div>
  );
}
