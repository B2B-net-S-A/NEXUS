"use client";

import { useId, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";

import { useToast } from "@/components/Toast";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  CompetenceCategoryBadge,
  useCompetenceCategories,
} from "@/components/v2/CompetenceCategoryBadge";
import { jobsApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useCategoryRecruiters,
  type CategoryRecruiter,
} from "@/lib/api/requestAllocation";
import { invalidateJobTeam } from "@/lib/job-team-cache";
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
 * Osoby z kategorii kompetencji są uczestnikami rekrutacji: widzą ją
 * w „Moja kategoria” i dostają jej powiadomienia, ale jej nie prowadzą — to
 * robi Rekruter. Lista jest zwinięta i wczytuje się dopiero po rozwinięciu
 * (bieżący skład kategorii, same aktywne konta).
 *
 * „Zmień” (tylko przy `canManage`) zapisuje kategorię od razu, jednym polem
 * w `PATCH /api/jobs/{id}`. Uczestnikami rekrutacji są osoby z jej kategorii,
 * więc po zmianie idą za nią — robi to serwer, w tle.
 */
export interface JobCategoryRowProps {
  categoryId: number | null;
  /** Rekrutacja, której kategorię zmienia „Zmień”; bez niej kontrolki nie ma. */
  jobId?: number;
  /** Pełna edycja rekrutacji (`can_manage`) — pokazuje „Zmień”. */
  canManage?: boolean;
}

export function JobCategoryRow({
  categoryId,
  jobId,
  canManage = false,
}: JobCategoryRowProps) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const catalog = useCompetenceCategories();
  const query = useCategoryRecruiters(categoryId, { enabled: open });
  const change =
    canManage && jobId != null ? (
      <CategoryChange jobId={jobId} categoryId={categoryId} />
    ) : null;

  if (categoryId == null) {
    return (
      <p className="text-xs leading-snug text-muted-foreground">
        Rekrutacja nie ma kategorii, więc nikt nie zobaczy jej w „Moja
        kategoria”.
        {change ? <> {change}</> : null}
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
        {change}
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
        Te osoby są uczestnikami rekrutacji: widzą ją w „Moja kategoria”
        i dostają jej powiadomienia. Prowadzi ją osoba z pola „Rekruter”.
      </p>
    </div>
  );
}

/**
 * „Zmień” / „Wybierz”: lista aktywnych kategorii, wybór zapisuje się od razu.
 * Katalog jest ten sam, z którego plakietka bierze nazwę (jedno zapytanie).
 */
function CategoryChange({
  jobId,
  categoryId,
}: {
  jobId: number;
  categoryId: number | null;
}) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const catalog = useCompetenceCategories();
  const [saving, setSaving] = useState(false);
  const options = catalog.data ?? [];

  const save = async (next: number) => {
    if (next === categoryId) return;
    setSaving(true);
    try {
      await jobsApi.update(jobId, { competence_category_id: next });
      showSuccess("Kategoria zmieniona — uczestnicy rekrutacji idą za nią.");
      // Rekrutacja, lista („Moja kategoria”) i pulpit „Requesty i obłożenie”.
      invalidateJobTeam(queryClient, jobId);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zmienić kategorii."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          disabled={saving}
          aria-label={categoryId == null ? "Wybierz kategorię" : "Zmień kategorię"}
          className="hit-area shrink-0 text-[11px] font-medium text-primary hover:underline disabled:opacity-50"
        >
          {saving ? "Zapisywanie…" : categoryId == null ? "Wybierz" : "Zmień"}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuLabel>Kategoria rekrutacji</DropdownMenuLabel>
        {/* Awaria katalogu to nie „brak kategorii”: osobny stan z ponowieniem,
            a pusty — dopiero po udanym odczycie. */}
        {catalog.isError && catalog.data === undefined ? (
          <DropdownMenuItem
            onSelect={(event) => {
              // Menu zostaje otwarte — po ponowieniu pokaże listę.
              event.preventDefault();
              void catalog.refetch();
            }}
          >
            Nie udało się pobrać kategorii — Ponów
          </DropdownMenuItem>
        ) : catalog.isPending ? (
          <DropdownMenuItem disabled>Ładowanie kategorii…</DropdownMenuItem>
        ) : options.length === 0 ? (
          <DropdownMenuItem disabled>Brak aktywnych kategorii.</DropdownMenuItem>
        ) : (
          <DropdownMenuRadioGroup
            value={categoryId != null ? String(categoryId) : ""}
            onValueChange={(value) => void save(Number(value))}
          >
            {options.map((category) => (
              <DropdownMenuRadioItem key={category.id} value={String(category.id)}>
                {category.name_pl}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
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
