"use client";

import type { ReactNode } from "react";
import { X } from "lucide-react";

import { shortenPersonName } from "@/lib/job-header-subtitle";
import { recruitersSummary, type RecruiterLike } from "@/lib/job-team";
import { cn } from "@/lib/utils";

export interface RecruiterChipsProps<T extends RecruiterLike = RecruiterLike> {
  /** Osoby w roli „Rekruter” — `recruitersOf(job)` albo `people` requestu z pulpitu. */
  people: readonly T[];
  size?: "sm" | "md";
  /** Komórka tabeli: samo nazwisko pierwszej osoby i „+N”, reszta w podpowiedzi. */
  compact?: boolean;
  /** Linia pod osobą, np. `assignedByCaption` („przydzielił(a) Anna L.”). */
  caption?: (person: T) => ReactNode;
  /** Podanie funkcji pokazuje przycisk „Zdejmij {imię i nazwisko}”. */
  onRemove?: (person: T) => void;
  /** Zawęża, przy kim przycisk się pojawia (np. `canRemoveRecruiter`). */
  canRemove?: (person: T) => boolean;
  /** Akcje pod propozycją automatu, np. „Akceptuj / Zmień / Odrzuć”. */
  proposalActions?: (person: T) => ReactNode;
  /** Co pokazać, gdy nie ma nikogo (domyślnie nic). */
  emptyLabel?: ReactNode;
  /** Nazwa listy dla czytników ekranu. */
  label?: string;
  className?: string;
}

const SIZES = {
  sm: {
    chip: "gap-1.5 py-0.5 pl-0.5 pr-1.5 text-xs",
    avatar: "h-5 w-5",
    indent: "pl-7",
    compact: "gap-1 text-xs",
  },
  md: {
    chip: "gap-2 py-0.5 pl-0.5 pr-2 text-sm",
    avatar: "h-6 w-6",
    indent: "pl-8",
    compact: "gap-1.5 text-sm",
  },
} as const;

/** „Jan Maria Rokita” → „JR”; jeden wyraz → dwie pierwsze litery. */
function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function Avatar({ name, className }: { name: string; className: string }) {
  return (
    <span
      aria-hidden="true"
      // Litery w kolorze tekstu, nie `text-primary`: na ciemnym motywie indygo
      // na przyciemnionym indygo ma kontrast 2,9:1 (zmierzone axe).
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full bg-primary/15 text-[10px] font-semibold text-foreground",
        className,
      )}
    >
      {initialsOf(name)}
    </span>
  );
}

/**
 * Osoby w roli „Rekruter”: awatar z inicjałami, imię i nazwisko.
 * Propozycja automatu ma przerywaną ramkę i dopisek
 * „propozycja” — to jeszcze nie praca. W wariancie `compact` (komórka tabeli)
 * zostaje samo nazwisko pierwszej osoby i „+N”.
 *
 * Komponent tylko rysuje. Dane, obsługę „Zdejmij” i akcje przy propozycjach
 * podaje ekran — tu nie ma zapytań ani zapisów.
 */
export function RecruiterChips<T extends RecruiterLike = RecruiterLike>({
  people,
  size = "md",
  compact = false,
  caption,
  onRemove,
  canRemove,
  proposalActions,
  emptyLabel,
  label,
  className,
}: RecruiterChipsProps<T>) {
  const sizes = SIZES[size];

  if (people.length === 0) return emptyLabel ? <>{emptyLabel}</> : null;

  if (compact) {
    const summary = recruitersSummary(people);
    // Nikt nie pracuje: pokazujemy pierwszą propozycję, przerywaną ramką.
    const proposedOnly = summary.lead === null;
    const firstName = proposedOnly ? summary.proposedNames[0] : summary.names[0];
    const more = proposedOnly
      ? summary.proposedNames.length - 1
      : summary.more;
    const moreBadge =
      more > 0 ? (
        <span
          aria-hidden="true"
          className="shrink-0 rounded-full bg-muted px-1.5 text-[10px] font-medium text-muted-foreground"
        >
          +{more}
        </span>
      ) : null;
    if (proposedOnly) {
      // Dwie linie (nazwisko, pod nim „propozycja”): w jednej linii chip miał
      // 120 px i poszerzał kolumnę „Rekruter” na laptopie, gdzie tabela listy
      // ledwo mieści się w oknie (pomiar 02.10.2026 przy 1280 px).
      return (
        <span
          title={summary.tooltip}
          data-proposed="true"
          className={cn(
            "relative inline-flex min-w-0 max-w-full flex-col rounded-md border border-dashed border-primary/60 px-2 py-0.5 leading-tight text-foreground",
            size === "sm" ? "text-xs" : "text-sm",
            className,
          )}
        >
          <span
            aria-hidden="true"
            className={cn("flex min-w-0 items-center whitespace-nowrap", sizes.compact)}
          >
            <span className="min-w-0 truncate">
              {shortenPersonName(firstName) ?? firstName}
            </span>
            {moreBadge}
          </span>
          <span aria-hidden="true" className="text-[11px] text-muted-foreground">
            propozycja
          </span>
          <span className="sr-only">{summary.tooltip}</span>
        </span>
      );
    }
    return (
      <span
        title={summary.tooltip}
        // `relative`: nazwiska dla czytników ekranu są pozycjonowane
        // absolutnie i mają zostać w obrębie komórki (przewijane tabele).
        className={cn(
          "relative inline-flex min-w-0 max-w-full items-center whitespace-nowrap text-foreground",
          sizes.compact,
          className,
        )}
      >
        <span aria-hidden="true" className="min-w-0 truncate">
          {summary.lead}
        </span>
        {moreBadge}
        <span className="sr-only">{summary.tooltip}</span>
      </span>
    );
  }

  return (
    <ul
      aria-label={label}
      className={cn("flex flex-wrap items-start gap-x-2 gap-y-1.5", className)}
    >
      {people.map((person) => {
        const removable =
          onRemove != null && (canRemove ? canRemove(person) : true);
        const note = caption?.(person);
        const actions = person.proposed ? proposalActions?.(person) : null;
        const tags = person.proposed ? "propozycja" : null;
        return (
          <li
            key={`${person.user_id}-${person.proposed ? "proposed" : "working"}`}
            className="flex min-w-0 max-w-full flex-col items-start gap-0.5"
          >
            <span
              data-proposed={person.proposed ? "true" : undefined}
              className={cn(
                "inline-flex max-w-full items-center rounded-full border",
                sizes.chip,
                person.proposed
                  ? "border-dashed border-primary/60"
                  : "border-border",
              )}
            >
              <Avatar name={person.name} className={sizes.avatar} />
              <span className="min-w-0 truncate text-foreground" title={person.name}>
                {person.name}
              </span>
              {/* W wąskiej kolumnie najpierw kurczy się etykieta, nazwisko dopiero
                  po niej. Współczynnik jest tak duży, żeby nazwisko nie traciło
                  nawet ułamka piksela (ucięcie z „…”) przed zniknięciem etykiety. */}
              {tags && (
                <span className="min-w-0 shrink-[1000000] truncate text-[11px] text-muted-foreground">
                  {tags}
                </span>
              )}
              {removable && (
                <button
                  type="button"
                  onClick={() => onRemove?.(person)}
                  aria-label={`Zdejmij ${person.name}`}
                  className="hit-area shrink-0 rounded-full p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                >
                  <X className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              )}
            </span>
            {note ? (
              <span
                className={cn(
                  "text-[11px] leading-tight text-muted-foreground",
                  sizes.indent,
                )}
              >
                {note}
              </span>
            ) : null}
            {actions ? (
              <div className={cn("flex flex-wrap items-center gap-x-2.5 gap-y-1", sizes.indent)}>
                {actions}
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
