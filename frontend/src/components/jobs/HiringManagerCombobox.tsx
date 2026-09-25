"use client";

import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronsUpDown, UserPlus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  fetchHiringManagerOptions,
  filterHiringManagerOptions,
  hiringManagerOptionsKey,
  looksLikePersonName,
  sameContact,
  type HiringManagerChoice,
} from "@/lib/hiring-manager";
import { cn } from "@/lib/utils";

interface Props {
  clientId: number | null;
  value: HiringManagerChoice | null;
  onChange: (value: HiringManagerChoice | null) => void;
  /** `id` etykiety pola — nazwa dostępna comboboxa. */
  labelledBy: string;
  disabled?: boolean;
}

/**
 * Hiring manager: osoba z kontaktów klienta albo wpisana ręcznie.
 *
 * Do 25.09.2026 był tu `<select>` z samymi kontaktami, a 10 z 23 klientów
 * z rekrutacjami nie miało żadnego — pola nie dało się wypełnić i HM stał na
 * 0 z 4349 rekrutacji. Ostatnia pozycja listy dodaje wpisaną osobę; serwer
 * zakłada ją jako kontakt klienta albo podpina istniejący (ta sama osoba
 * wpisana inaczej nie staje się duplikatem). Komponent tylko wybiera —
 * zapisuje wołający (`saveHiringManager`).
 */
export function HiringManagerCombobox({
  clientId,
  value,
  onChange,
  labelledBy,
  disabled = false,
}: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState<{
    name: string;
    position: string;
    email: string;
  } | null>(null);
  const ids = { name: useId(), position: useId(), email: useId() };

  const optionsQuery = useQuery({
    queryKey: hiringManagerOptionsKey(clientId),
    queryFn: () => fetchHiringManagerOptions(clientId as number),
    enabled: open && clientId != null,
    staleTime: 5 * 60 * 1000,
  });
  const options = optionsQuery.data ?? [];
  const visible = filterHiringManagerOptions(options, query);
  const typed = query.trim();
  const exact = sameContact(options, typed);

  const close = () => {
    setOpen(false);
    setQuery("");
    setDraft(null);
  };
  const pick = (choice: HiringManagerChoice | null) => {
    onChange(choice);
    close();
  };

  const noClient = clientId == null;
  const draftValid = draft !== null && looksLikePersonName(draft.name);
  const confirmDraft = () => {
    if (draft === null || !draftValid) return;
    pick({
      kind: "new",
      name: draft.name.trim(),
      position: draft.position.trim() || null,
      email: draft.email.trim() || null,
    });
  };

  return (
    <Popover open={open} onOpenChange={(next) => (next ? setOpen(true) : close())}>
      <PopoverTrigger asChild>
        <button
          type="button"
          role="combobox"
          aria-expanded={open}
          aria-labelledby={labelledBy}
          disabled={disabled || noClient}
          className="w-full flex items-center justify-between gap-2 rounded-lg border border-border bg-card px-3 py-2 text-left text-sm focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
        >
          <span className={cn("truncate", !value && "text-muted-foreground")}>
            {noClient
              ? "Najpierw wybierz klienta"
              : value
                ? value.name
                : "Wybierz albo wpisz osobę…"}
            {value?.kind === "new" ? (
              <span className="ml-1.5 text-xs text-muted-foreground">(nowa osoba)</span>
            ) : null}
          </span>
          <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-(--radix-popover-trigger-width) min-w-72 p-0">
        {draft ? (
          // `div`, nie `<form>`: zdarzenia Reacta przechodzą przez portal, więc
          // `submit` stąd wysłałby formularz edycji rekrutacji, w którym stoi pole.
          <div
            className="flex flex-col gap-2 p-3"
            onKeyDown={(e) => {
              if (e.key !== "Enter") return;
              e.preventDefault();
              e.stopPropagation();
              confirmDraft();
            }}
          >
            <p className="text-xs text-muted-foreground">
              Osoba zostanie zapisana w kontaktach klienta.
            </p>
            <label htmlFor={ids.name} className="text-xs font-medium">
              Imię i nazwisko
            </label>
            <Input
              id={ids.name}
              autoFocus
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              aria-invalid={!draftValid}
            />
            {!draftValid ? (
              <p className="text-xs text-destructive">Podaj imię i nazwisko.</p>
            ) : null}
            <label htmlFor={ids.position} className="text-xs font-medium">
              Stanowisko (opcjonalnie)
            </label>
            <Input
              id={ids.position}
              value={draft.position}
              onChange={(e) => setDraft({ ...draft, position: e.target.value })}
            />
            <label htmlFor={ids.email} className="text-xs font-medium">
              E-mail (opcjonalnie)
            </label>
            <Input
              id={ids.email}
              type="email"
              value={draft.email}
              onChange={(e) => setDraft({ ...draft, email: e.target.value })}
            />
            <div className="mt-1 flex justify-end gap-2">
              <Button type="button" variant="ghost" size="sm" onClick={() => setDraft(null)}>
                Wróć do listy
              </Button>
              <Button type="button" size="sm" disabled={!draftValid} onClick={confirmDraft}>
                Wybierz
              </Button>
            </div>
          </div>
        ) : (
          <Command shouldFilter={false}>
            <CommandInput
              placeholder="Szukaj albo wpisz imię i nazwisko…"
              value={query}
              onValueChange={setQuery}
            />
            <CommandList>
              {optionsQuery.isLoading ? (
                <div className="p-3 text-sm text-muted-foreground">Wczytuję kontakty…</div>
              ) : optionsQuery.isError ? (
                // Awaria ≠ „klient nie ma kontaktów" — wpisanie osoby nadal działa.
                <div className="p-3 text-sm text-destructive" role="alert">
                  Nie udało się wczytać kontaktów klienta. Możesz wpisać osobę ręcznie.
                </div>
              ) : typed ? null : (
                <CommandEmpty>Ten klient nie ma jeszcze kontaktów — wpisz osobę.</CommandEmpty>
              )}
              <CommandGroup>
                {/* Tylko przy pustym wpisie: cmdk podświetla pierwszą pozycję,
                    więc Enter po wpisaniu nazwiska nie może czyścić pola. */}
                {value && !typed ? (
                  <CommandItem value="__none__" onSelect={() => pick(null)}>
                    <X className="mr-2 h-4 w-4" />
                    Bez hiring managera
                  </CommandItem>
                ) : null}
                {visible.map((o) => (
                  <CommandItem
                    key={o.id}
                    value={`contact-${o.id}`}
                    onSelect={() => pick({ kind: "contact", id: o.id, name: o.name })}
                  >
                    <Check
                      className={cn(
                        "mr-2 h-4 w-4",
                        value?.kind === "contact" && value.id === o.id
                          ? "opacity-100"
                          : "opacity-0",
                      )}
                    />
                    <span className="truncate">
                      {o.name}
                      {o.position ? (
                        <span className="ml-1 text-xs text-muted-foreground">{o.position}</span>
                      ) : null}
                    </span>
                  </CommandItem>
                ))}
                {typed && !exact ? (
                  <CommandItem
                    value="__create__"
                    onSelect={() => setDraft({ name: typed, position: "", email: "" })}
                  >
                    <UserPlus className="mr-2 h-4 w-4" />
                    <span className="truncate">
                      Dodaj „{typed}” jako nowego hiring managera
                    </span>
                  </CommandItem>
                ) : null}
              </CommandGroup>
            </CommandList>
          </Command>
        )}
      </PopoverContent>
    </Popover>
  );
}

export default HiringManagerCombobox;
