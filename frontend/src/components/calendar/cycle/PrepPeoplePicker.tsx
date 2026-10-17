"use client";

import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Plus, X } from "lucide-react";

import type { PrepPersonOption } from "@/lib/api/prepMeetings";
import {
  MAX_INVITEES,
  addEmail,
  addUser,
  isEmailAddress,
  removeEmail,
  removeUser,
  searchPeople,
  type Invitees,
} from "@/lib/prep-people";
import { cn } from "@/lib/utils";
import { ROLE_LABELS, type UserRole } from "@/store/auth";

type Option =
  | { kind: "person"; person: PrepPersonOption }
  | { kind: "email"; email: string };

function roleLabel(role: string | null): string | null {
  return role && role in ROLE_LABELS ? ROLE_LABELS[role as UserRole] : null;
}

/**
 * Pole „Zaproś” okien prepu (17.10.2026, decyzja D1): osoby z całego NEXUSA
 * wyszukiwane po nazwisku i dowolny adres e-mail. Do tej daty okno pokazywało
 * cały zespół rekrutacji jako przyciski (u Nordei 13 osób, razem z adminami)
 * i nikogo spoza niego nie dało się dopisać.
 *
 * `exclude` — prowadzący (jest organizatorem, nie zaproszonym).
 */
export function PrepPeoplePicker({
  id,
  label,
  people,
  value,
  onChange,
  exclude,
  currentUserId,
  recommended = [],
  names = {},
}: {
  id: string;
  label: string;
  people: readonly PrepPersonOption[];
  value: Invitees;
  onChange: (next: Invitees) => void;
  exclude: ReadonlySet<number>;
  currentUserId?: number | null;
  recommended?: readonly PrepPersonOption[];
  /** Nazwiska zaproszonych spoza listy `people` (np. konto już nieaktywne). */
  names?: Readonly<Record<number, string>>;
}) {
  const listId = useId();
  const listRef = useRef<HTMLUListElement>(null);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);

  const taken = useMemo(() => new Set([...exclude, ...value.userIds]), [exclude, value.userIds]);
  const matches = useMemo(() => searchPeople(people, query, taken), [people, query, taken]);
  const typedEmail = isEmailAddress(query) ? query.trim() : null;
  const options: Option[] = [
    ...matches.map((person) => ({ kind: "person" as const, person })),
    ...(typedEmail ? [{ kind: "email" as const, email: typedEmail }] : []),
  ];
  const open = query.trim().length > 0;
  // Pole stoi nisko w oknie, które przewija się w środku — na laptopie
  // 1280×720 lista wyników otwierała się poniżej widocznej części okna.
  useEffect(() => {
    if (open) listRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [open]);
  const full = value.userIds.length >= MAX_INVITEES && value.emails.length >= MAX_INVITEES;

  const nameOf = (uid: number) =>
    people.find((p) => p.id === uid)?.name ?? names[uid] ?? `Osoba #${uid}`;
  const roleOf = (uid: number) => roleLabel(people.find((p) => p.id === uid)?.role ?? null);

  const pick = (option: Option) => {
    onChange(option.kind === "person" ? addUser(value, option.person.id) : addEmail(value, option.email));
    setQuery("");
    setActive(0);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" && options.length) {
      e.preventDefault();
      setActive((i) => (i + 1) % options.length);
    } else if (e.key === "ArrowUp" && options.length) {
      e.preventDefault();
      setActive((i) => (i - 1 + options.length) % options.length);
    } else if (e.key === "Enter" || e.key === ",") {
      if (!open) return;
      e.preventDefault();
      const option = options[Math.min(active, options.length - 1)];
      if (option) pick(option);
    } else if (e.key === "Escape" && open) {
      e.stopPropagation();
      setQuery("");
    } else if (e.key === "Backspace" && !query) {
      if (value.emails.length) onChange(removeEmail(value, value.emails[value.emails.length - 1]));
      else if (value.userIds.length) onChange(removeUser(value, value.userIds[value.userIds.length - 1]));
    }
  };

  const team = matches.filter((p) => p.in_team);
  const others = matches.filter((p) => !p.in_team);
  const optionIndex = (option: Option) =>
    options.findIndex((o) =>
      option.kind === "person"
        ? o.kind === "person" && o.person.id === option.person.id
        : o.kind === "email",
    );
  const optionId = (i: number) => `${listId}-opt-${i}`;

  const renderPerson = (person: PrepPersonOption) => {
    const i = optionIndex({ kind: "person", person });
    const role = roleLabel(person.role);
    return (
      <li
        key={person.id}
        id={optionId(i)}
        role="option"
        aria-selected={i === active}
        onMouseDown={(e) => {
          e.preventDefault();
          pick({ kind: "person", person });
        }}
        onMouseEnter={() => setActive(i)}
        className={cn(
          "flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm",
          i === active && "bg-muted",
        )}
      >
        <span className="font-medium text-foreground">{person.name}</span>
        {role ? <span className="text-xs text-muted-foreground">· {role}</span> : null}
        {!person.in_team ? (
          <span className="text-xs text-muted-foreground">· spoza zespołu rekrutacji</span>
        ) : null}
      </li>
    );
  };

  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-semibold text-muted-foreground">
        {label}
      </label>
      <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-border bg-card px-2 py-1.5 focus-within:ring-2 focus-within:ring-ring">
        {value.userIds.map((uid) => {
          const name = nameOf(uid);
          const role = roleOf(uid);
          return (
            <span
              key={`u-${uid}`}
              className="inline-flex items-center gap-1 rounded-full bg-primary/10 py-0.5 pl-2.5 pr-1 text-xs font-medium text-primary"
            >
              {name}
              {uid === currentUserId ? " · Ty" : role ? ` · ${role}` : ""}
              <button
                type="button"
                aria-label={`Usuń ${name}`}
                onClick={() => onChange(removeUser(value, uid))}
                className="inline-flex h-5 w-5 items-center justify-center rounded-full hover:bg-primary/15"
              >
                <X className="h-3 w-3" aria-hidden />
              </button>
            </span>
          );
        })}
        {value.emails.map((email) => (
          <span
            key={`e-${email}`}
            className="inline-flex items-center gap-1 rounded-full bg-warning-muted py-0.5 pl-2.5 pr-1 text-xs font-medium text-warning-muted-foreground"
          >
            {email} · spoza NEXUSA
            <button
              type="button"
              aria-label={`Usuń ${email}`}
              onClick={() => onChange(removeEmail(value, email))}
              className="inline-flex h-5 w-5 items-center justify-center rounded-full hover:bg-warning/15"
            >
              <X className="h-3 w-3" aria-hidden />
            </button>
          </span>
        ))}
        <input
          id={id}
          type="text"
          role="combobox"
          autoComplete="off"
          aria-expanded={open}
          aria-controls={listId}
          aria-activedescendant={open && options.length ? optionId(active) : undefined}
          placeholder={full ? "Lista jest pełna" : "Dodaj osobę albo adres e-mail"}
          disabled={full}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
          onBlur={() => {
            // Wpisany cały adres nie ginie, gdy ktoś kliknie dalej zamiast Enter.
            if (typedEmail) pick({ kind: "email", email: typedEmail });
          }}
          className="min-w-[10rem] flex-1 bg-transparent px-1 py-1 text-sm outline-hidden"
        />
      </div>
      {open ? (
        <ul
          ref={listRef}
          id={listId}
          role="listbox"
          aria-label="Wyniki wyszukiwania"
          className="mt-1 max-h-64 overflow-y-auto rounded-md border border-border bg-popover py-1 shadow-md"
        >
          {team.length ? (
            <li role="presentation" className="px-3 pb-0.5 pt-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Zespół tej rekrutacji
            </li>
          ) : null}
          {team.map(renderPerson)}
          {others.length ? (
            <li role="presentation" className="px-3 pb-0.5 pt-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Wszyscy w NEXUSIE
            </li>
          ) : null}
          {others.map(renderPerson)}
          {typedEmail ? (
            <li
              id={optionId(optionIndex({ kind: "email", email: typedEmail }))}
              role="option"
              aria-selected={optionIndex({ kind: "email", email: typedEmail }) === active}
              onMouseDown={(e) => {
                e.preventDefault();
                pick({ kind: "email", email: typedEmail });
              }}
              className={cn(
                "cursor-pointer px-3 py-1.5 text-sm",
                optionIndex({ kind: "email", email: typedEmail }) === active && "bg-muted",
              )}
            >
              Zaproś adres <span className="font-medium">{typedEmail}</span>
            </li>
          ) : null}
          {options.length === 0 ? (
            <li role="presentation" className="px-3 py-1.5 text-xs text-muted-foreground">
              Nikogo takiego nie ma w NEXUSIE. Wpisz cały adres e-mail, żeby zaprosić kogoś spoza.
            </li>
          ) : null}
        </ul>
      ) : null}
      {recommended.length ? (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted-foreground">Polecani:</span>
          {recommended.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => onChange(addUser(value, p.id))}
              className="inline-flex items-center gap-1 rounded-full border border-dashed border-border px-2.5 py-1 hover:bg-muted"
            >
              <Plus className="h-3 w-3" aria-hidden />
              {p.name}
              {roleLabel(p.role) ? ` · ${roleLabel(p.role)}` : ""}
            </button>
          ))}
        </div>
      ) : null}
      {value.emails.length ? (
        <p className="mt-2 rounded-md bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
          Osoby spoza NEXUSA dostaną zaproszenie z tą samą informacją o nagrywaniu co kandydat.
          Transkrypt zostaje w NEXUSIE.
        </p>
      ) : null}
    </div>
  );
}
