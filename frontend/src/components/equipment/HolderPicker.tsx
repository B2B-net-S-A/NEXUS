"use client";

import { useDeferredValue, useState } from "react";
import { Search, UserPlus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import { useAcademyHolderSearch } from "@/lib/api/academy-edition";
import {
  useCreateExternalPerson,
  useHolderSearch,
  type EquipmentHolder,
} from "@/lib/api/equipment";

import { HOLDER_KIND_LABELS } from "./equipment-format";

interface HolderPickerProps {
  value: EquipmentHolder | null;
  onChange: (holder: EquipmentHolder | null) => void;
  /**
   * Kreator wydania: przełącznik „Uczestnik Akademii” (zgłoszenie po zaliczonym
   * zadaniu). Bez niego (import plików, zwrot z rejestru) uczestnika nie wybierzesz.
   */
  academy?: boolean;
  /**
   * Tylko aktywne konta NEXUSA — „Przepisz na konto” osoby spoza NEXUSA.
   * Bez kontraktów, osób spoza i dodawania nowej osoby.
   */
  accountsOnly?: boolean;
}

type SearchMode = "registry" | "academy";

/** Wybór posiadacza: konto NEXUSA, kontrakt konsultanta, osoba spoza albo uczestnik Akademii. */
export function HolderPicker({
  value,
  onChange,
  academy: withAcademy = false,
  accountsOnly = false,
}: HolderPickerProps) {
  const [mode, setMode] = useState<SearchMode>("registry");
  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query);
  const academyMode = withAcademy && mode === "academy";
  const registry = useHolderSearch(academyMode ? "" : deferred);
  const academy = useAcademyHolderSearch(deferred, academyMode);
  const results = academyMode ? academy : registry;
  const found: EquipmentHolder[] = (academyMode ? academy.data : registry.data) ?? [];
  const hits = accountsOnly ? found.filter((holder) => holder.kind === "user") : found;
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const create = useCreateExternalPerson();

  const choose = (holder: EquipmentHolder | null) => {
    // Import plików i zwrot z rejestru nie przyjmują uczestnika Akademii.
    if (holder?.kind === "academy" && !withAcademy) return;
    if (holder && accountsOnly && holder.kind !== "user") return;
    onChange(holder);
  };

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
        <Button variant="ghost" size="sm" className="ml-auto" onClick={() => choose(null)}>
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
          choose({
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
      {withAcademy ? (
        <div role="group" aria-label="Kogo szukasz" className="flex gap-1">
          {(
            [
              ["registry", "Pracownik, konsultant, osoba spoza"],
              ["academy", "Uczestnik Akademii"],
            ] as const
          ).map(([key, label]) => (
            <Button
              key={key}
              size="sm"
              variant={mode === key ? "secondary" : "ghost"}
              aria-pressed={mode === key}
              onClick={() => {
                setMode(key);
                setAdding(false);
              }}
            >
              {label}
            </Button>
          ))}
        </div>
      ) : null}
      <div className="relative">
        <Search
          aria-hidden
          className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
        />
        <Input
          autoFocus
          aria-label={
            academyMode
              ? "Szukaj uczestnika Akademii"
              : accountsOnly
                ? "Szukaj konta NEXUSA"
                : "Szukaj osoby albo kontraktu"
          }
          placeholder={
            academyMode ? "Imię i nazwisko uczestnika Akademii…" : "Imię i nazwisko albo e-mail…"
          }
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
        ) : results.isSuccess && hits.length === 0 ? (
          academyMode ? (
            <p className="text-sm text-muted-foreground">Nikt nie pasuje do „{deferred}”.</p>
          ) : (
            <NoMatch query={deferred} accountsOnly={accountsOnly} />
          )
        ) : (
          <ul className="max-h-64 divide-y divide-border overflow-y-auto rounded-md border border-border">
            {hits.map((holder) => (
              <li key={`${holder.kind}-${holder.id}`}>
                <button
                  type="button"
                  className="flex w-full items-baseline gap-2 px-3 py-2 text-left text-sm hover:bg-muted"
                  onClick={() => choose(holder)}
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
      {accountsOnly ? null : academyMode ? (
        <p className="text-xs text-muted-foreground">
          Uczestnik po zaliczonym zadaniu w Akademii; imię, nazwisko i e-mail do protokołu
          pochodzą ze zgłoszenia.
        </p>
      ) : adding ? (
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

/** Pusty wynik w rejestrze: gdzie szukaliśmy i co zrobić z nową osobą bez konta. */
function NoMatch({ query, accountsOnly }: { query: string; accountsOnly: boolean }) {
  return (
    <div className="space-y-1 rounded-md border border-border bg-muted/40 px-3 py-2 text-sm">
      <p className="font-medium">Nikt nie pasuje do „{query}”.</p>
      {accountsOnly ? (
        <p className="text-xs text-muted-foreground">
          Szukam wśród aktywnych kont NEXUSA. Jeśli konta jeszcze nie ma, przepiszesz sprzęt, gdy
          powstanie.
        </p>
      ) : (
        <>
          <p className="text-xs text-muted-foreground">
            Szukam wśród aktywnych kont NEXUSA, kontraktów konsultantów (od szkicu do zakończenia)
            i osób spoza NEXUSA.
          </p>
          <p className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground">Nowa osoba w firmie?</span> Sprzęt wydasz
            jej od razu jako osobie spoza NEXUSA, a gdy powstanie konto, przepiszesz go jednym
            kliknięciem („Przepisz na konto” w menu ⋯ wiersza).
          </p>
        </>
      )}
    </div>
  );
}
