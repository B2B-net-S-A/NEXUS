"use client";

import { useId, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import {
  CompetenceCategoryBadge,
  useCompetenceCategories,
} from "@/components/v2/CompetenceCategoryBadge";
import {
  useCategoryRecruiters,
  type CategoryRecruiter,
} from "@/lib/api/requestAllocation";
import { countPl } from "@/lib/plural-pl";

/** 1. priorytet przed 2., potem osoby bez priorytetu; w grupie alfabetycznie. */
function byPriorityThenName(a: CategoryRecruiter, b: CategoryRecruiter): number {
  return (
    (a.priority ?? 9) - (b.priority ?? 9) || a.name.localeCompare(b.name, "pl")
  );
}

/**
 * Wiersz „Kategoria” panelu zespołu (decyzja Artura 02.10.2026).
 *
 * Kategoria kompetencji mówi, kto MOŻE wziąć rekrutację i kto widzi ją
 * w „Moja kategoria” — nic więcej. Do tej zmiany osoby z kategorii stały
 * w panelu jako „współpracownicy”, czyli wyglądały, jakby nad rekrutacją
 * pracowały. Lista jest zwinięta i wczytuje się dopiero po rozwinięciu
 * (bieżący skład kategorii, same aktywne konta).
 */
export function JobCategoryRow({ categoryId }: { categoryId: number | null }) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const catalog = useCompetenceCategories();
  const query = useCategoryRecruiters(categoryId, { enabled: open });

  if (categoryId == null) {
    return (
      <p className="text-xs leading-snug text-muted-foreground">
        Rekrutacja nie ma kategorii, więc nikt nie zobaczy jej w „Moja
        kategoria”.
      </p>
    );
  }

  // Plakietka nie rysuje nic, gdy katalog nie zna kategorii albo się nie
  // wczytał — puste miejsce czytałoby się jak „brak kategorii”.
  const nameMissing =
    !catalog.isPending &&
    !(catalog.data ?? []).some((category) => category.id === categoryId);
  // Liczba osób jest znana dopiero po wczytaniu listy (albo z pamięci podręcznej).
  const people = query.data ? [...query.data].sort(byPriorityThenName) : null;

  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <CompetenceCategoryBadge categoryId={categoryId} size="md" />
        {nameMissing ? (
          <span className="text-xs text-muted-foreground">
            {catalog.isError
              ? "Nie udało się pobrać nazwy kategorii"
              : "Kategoria spoza aktywnej listy"}
          </span>
        ) : null}
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-controls={listId}
          className="hit-area inline-flex items-center gap-0.5 text-[11px] font-medium text-primary hover:underline"
        >
          {people
            ? countPl(
                people.length,
                "osoba z kategorii",
                "osoby z kategorii",
                "osób z kategorii",
              )
            : "Osoby z kategorii"}
          {open ? (
            <ChevronDown className="h-3 w-3 shrink-0" aria-hidden="true" />
          ) : (
            <ChevronRight className="h-3 w-3 shrink-0" aria-hidden="true" />
          )}
        </button>
      </div>

      <div id={listId} hidden={!open}>
        {open ? (
          <CategoryPeople
            people={people}
            isError={query.isError}
            isSuccess={query.isSuccess}
            onRetry={() => void query.refetch()}
          />
        ) : null}
      </div>

      <p className="text-[11px] leading-snug text-muted-foreground">
        Te osoby widzą rekrutację w „Moja kategoria”, ale nie pracują nad nią,
        dopóki ktoś ich nie przydzieli.
      </p>
    </div>
  );
}

function CategoryPeople({
  people,
  isError,
  isSuccess,
  onRetry,
}: {
  people: CategoryRecruiter[] | null;
  isError: boolean;
  isSuccess: boolean;
  onRetry: () => void;
}) {
  // Awaria to nie „pusta kategoria” — osobny stan z ponowieniem. Sprawdzamy ją
  // przed danymi: po nieudanym odświeżeniu stara lista udawałaby aktualną.
  if (isError) {
    return (
      <p role="alert" className="text-[11px] leading-snug text-muted-foreground">
        Nie udało się pobrać osób z kategorii.{" "}
        <button
          type="button"
          onClick={onRetry}
          className="hit-area font-medium text-primary hover:underline"
        >
          Ponów
        </button>
      </p>
    );
  }
  if (!isSuccess || people == null) {
    return (
      <p role="status" className="text-[11px] text-muted-foreground">
        Ładowanie osób z kategorii…
      </p>
    );
  }
  if (people.length === 0) {
    return (
      <p className="text-[11px] leading-snug text-muted-foreground">
        Nikt nie ma dziś tej kategorii.
      </p>
    );
  }
  return (
    <ul aria-label="Osoby z kategorii" className="space-y-0.5 text-xs text-foreground">
      {people.map((person) => (
        <li key={person.user_id} className="flex min-w-0 items-baseline gap-1.5">
          <span className="min-w-0 truncate" title={person.name}>
            {person.name}
          </span>
          {person.priority != null ? (
            <span className="shrink-0 text-[11px] text-muted-foreground">
              {person.priority}. priorytet
            </span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
