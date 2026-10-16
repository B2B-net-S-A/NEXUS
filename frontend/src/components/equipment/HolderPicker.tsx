"use client";

import { useDeferredValue, useState } from "react";
import { Search, UserPlus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useCreateExternalPerson,
  useHolderSearch,
  type EquipmentHolder,
} from "@/lib/api/equipment";

import { HOLDER_KIND_LABELS } from "./equipment-format";

interface HolderPickerProps {
  value: EquipmentHolder | null;
  onChange: (holder: EquipmentHolder | null) => void;
}

/** Wybór posiadacza: konto NEXUSA, kontrakt konsultanta albo osoba spoza (np. Akademia). */
export function HolderPicker({ value, onChange }: HolderPickerProps) {
  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query);
  const results = useHolderSearch(deferred);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const create = useCreateExternalPerson();

  if (value) {
    return (
      <div className="flex items-center gap-3 rounded-md border border-border bg-muted/40 px-3 py-2 text-sm">
        <span className="grid h-8 w-8 place-items-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
          {value.name
            .split(/\s+/)
            .filter(Boolean)
            .map((part) => part[0])
            .slice(0, 2)
            .join("")
            .toUpperCase()}
        </span>
        <span className="min-w-0">
          <span className="block font-medium">{value.name}</span>
          <span className="block text-xs text-muted-foreground">
            {/* api-detail-ok: `detail` to podpis posiadacza z listy, nie błąd API */}
            {value.detail ?? HOLDER_KIND_LABELS[value.kind]}
            {value.email ? ` · ${value.email}` : ""}
          </span>
        </span>
        <Button variant="ghost" size="sm" className="ml-auto" onClick={() => onChange(null)}>
          Zmień
        </Button>
      </div>
    );
  }

  const addExternal = () => {
    setError(null);
    create.mutate(
      { full_name: name.trim(), work_email: email.trim() || null, note: note.trim() || null },
      {
        onSuccess: (person) =>
          onChange({
            kind: "external",
            id: person.id,
            name: person.full_name,
            email: person.work_email,
            detail: person.note ?? HOLDER_KIND_LABELS.external,
          }),
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się dodać osoby.")),
      },
    );
  };

  return (
    <div className="space-y-2">
      <div className="relative">
        <Search
          aria-hidden
          className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
        />
        <Input
          autoFocus
          aria-label="Szukaj osoby albo kontraktu"
          placeholder="Imię i nazwisko pracownika albo konsultanta…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="pl-8"
        />
      </div>
      {deferred.trim().length >= 2 ? (
        results.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {apiErrorMessage(results.error, "Nie udało się wyszukać osób.")}
          </p>
        ) : results.isSuccess && results.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nikt nie pasuje do „{deferred}”.</p>
        ) : (
          <ul className="max-h-64 divide-y divide-border overflow-y-auto rounded-md border border-border">
            {(results.data ?? []).map((holder) => (
              <li key={`${holder.kind}-${holder.id}`}>
                <button
                  type="button"
                  className="flex w-full items-baseline gap-2 px-3 py-2 text-left text-sm hover:bg-muted"
                  onClick={() => onChange(holder)}
                >
                  <span className="font-medium">{holder.name}</span>
                  <span className="text-xs text-muted-foreground">{holder.detail}</span>
                </button>
              </li>
            ))}
          </ul>
        )
      ) : (
        <p className="text-xs text-muted-foreground">Wpisz co najmniej dwie litery.</p>
      )}
      {adding ? (
        <div className="grid gap-2 rounded-md border border-border p-3 sm:grid-cols-3">
          <FormField label="Imię i nazwisko" htmlFor="eq-ext-name" required>
            <Input id="eq-ext-name" value={name} onChange={(e) => setName(e.target.value)} />
          </FormField>
          <FormField label="E-mail służbowy" htmlFor="eq-ext-email">
            <Input id="eq-ext-email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </FormField>
          <FormField label="Kto to" htmlFor="eq-ext-note">
            <Input
              id="eq-ext-note"
              placeholder="np. Akademia 11.2026"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </FormField>
          <div className="flex items-center gap-2 sm:col-span-3">
            <Button size="sm" onClick={addExternal} disabled={!name.trim() || create.isPending}>
              Dodaj osobę
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setAdding(false)}>
              Anuluj
            </Button>
            {error ? (
              <span role="alert" className="text-xs text-destructive">
                {error}
              </span>
            ) : null}
          </div>
        </div>
      ) : (
        <Button variant="tertiary" size="sm" onClick={() => setAdding(true)}>
          <UserPlus className="h-4 w-4" aria-hidden />
          Osoba spoza NEXUSA
        </Button>
      )}
    </div>
  );
}
