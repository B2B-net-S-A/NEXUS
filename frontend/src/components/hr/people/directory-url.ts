"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";

import type { EmploymentType } from "@/lib/api/hr";
import { useUrlWriter } from "@/lib/url-selection";

/**
 * Filtry i widok katalogu „Ludzi” w adresie (22.10.2026): „← Ludzie”
 * z kartoteki wraca do tej samej, przefiltrowanej listy. Zapis przez
 * `useUrlWriter` (natywna historia, bez przewijania — patrz
 * docs/claude/ui/parametry-adresu-natywna-historia-nie-router-replace.md).
 */

export type DirectoryView = "lista" | "schemat";
export type StatusFilter = "away" | "leaving" | "no_report";

export interface DirectoryFilters {
  q: string;
  department: string | null;
  form: EmploymentType | null;
  status: StatusFilter | null;
  view: DirectoryView;
}

/** Nazwy parametrów adresu. */
const PARAM = {
  q: "q",
  department: "department",
  form: "form",
  status: "status",
  view: "view",
} as const;

const FORMS: readonly EmploymentType[] = ["b2b", "uop", "zlecenie"];
const STATUSES: readonly StatusFilter[] = ["away", "leaving", "no_report"];
const VIEWS: readonly DirectoryView[] = ["lista", "schemat"];

function pick<T extends string>(raw: string | null, known: readonly T[]): T | null {
  return raw !== null && (known as readonly string[]).includes(raw) ? (raw as T) : null;
}

/** Adres → filtry; nieznane wartości (stary albo ręcznie zmieniony link) = brak filtra. */
export function readDirectoryParams(
  params: URLSearchParams | null,
  defaultView: DirectoryView = "lista",
): DirectoryFilters {
  const get = (name: string) => params?.get(name) ?? null;
  const department = get(PARAM.department)?.trim();
  return {
    q: get(PARAM.q) ?? "",
    department: department ? department : null,
    form: pick(get(PARAM.form), FORMS),
    status: pick(get(PARAM.status), STATUSES),
    view: pick(get(PARAM.view), VIEWS) ?? defaultView,
  };
}

/** Bieżący adres z podmienionymi parametrami katalogu (inne parametry zostają). */
export function directoryHref(
  pathname: string,
  search: string,
  filters: DirectoryFilters,
  defaultView: DirectoryView = "lista",
): string {
  const params = new URLSearchParams(search);
  const set = (name: string, value: string | null) => {
    if (value) params.set(name, value);
    else params.delete(name);
  };
  set(PARAM.q, filters.q.trim() ? filters.q : null);
  set(PARAM.department, filters.department);
  set(PARAM.form, filters.form);
  set(PARAM.status, filters.status);
  set(PARAM.view, filters.view === defaultView ? null : filters.view);
  const query = params.toString();
  return query ? `${pathname}?${query}` : pathname;
}

/** `/people/structure?…` → `/people?view=schemat&…` (dawna zakładka „Struktura”). */
export function structureRedirectHref(search: string): string {
  const params = new URLSearchParams(search);
  params.set(PARAM.view, "schemat");
  return `/people?${params.toString()}`;
}

function filtersKey(filters: DirectoryFilters): string {
  return JSON.stringify([filters.q, filters.department, filters.form, filters.status, filters.view]);
}

/**
 * Stan filtrów z adresu. Adres jest źródłem prawdy, gdy różni się od stanu
 * (miękka nawigacja na goły `/people`, „Wstecz”) — inicjalizator `useState`
 * sam by tego nie zobaczył. Pole wyszukiwania trzyma stan lokalnie, więc
 * pisanie nie czeka na odświeżenie `useSearchParams`.
 */
export function useDirectoryFilters(defaultView: DirectoryView = "lista") {
  const searchParams = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const search = searchParams?.toString() ?? "";
  const fromUrl = useMemo(
    () => readDirectoryParams(new URLSearchParams(search), defaultView),
    [search, defaultView],
  );
  const [filters, setFilters] = useState<DirectoryFilters>(fromUrl);
  const current = useRef(filters);
  current.current = filters;

  const urlKey = filtersKey(fromUrl);
  useEffect(() => {
    if (filtersKey(current.current) !== urlKey) setFilters(fromUrl);
    // `fromUrl` zmienia się razem z `urlKey`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlKey]);

  const update = useCallback(
    (patch: Partial<DirectoryFilters>) => {
      const next = { ...current.current, ...patch };
      current.current = next;
      setFilters(next);
      replaceUrl(
        directoryHref(window.location.pathname, window.location.search, next, defaultView),
      );
    },
    [replaceUrl, defaultView],
  );

  return [filters, update] as const;
}
