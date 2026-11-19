"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface SectionNavItem {
  key: string;
  label: string;
  /** Inna trasa albo adres z `?view=` — wtedy pozycja jest linkiem. */
  href?: string;
  /** Licznik spraw do zrobienia; 0/brak = bez plakietki. */
  count?: number;
  /** Dostępna nazwa licznika, np. „24 do zrobienia w bieżącym miesiącu”. */
  countLabel?: string;
  /**
   * Kotwica nowości (`data-tour`) na pozycji. Id wpisz w wywołaniu razem
   * z komentarzem `// data-tour="…"` w tej samej linii — strażnik kotwic
   * (`novelty-anchors.test.ts`) szuka ich dosłownie.
   */
  tourId?: string;
}

export interface SectionNavGroup {
  key: string;
  label: string;
  items: SectionNavItem[];
  /**
   * Cicha liczba przy nazwie grupy („Nasi ludzie 32”) — ile tam jest, nie ile
   * do zrobienia (to `count` pozycji, plakietka w kolorze).
   */
  meta?: string;
  /** Kotwica nowości na grupie (zasady jak `SectionNavItem.tourId`). */
  tourId?: string;
}

export interface SectionNavProps {
  label: string;
  groups: SectionNavGroup[];
  activeItem: string;
  /** Wybór w miejscu (bez zmiany trasy) — dla pozycji bez `href`. */
  onSelect?: (itemKey: string) => void;
  className?: string;
  /** Wcięcie pasków, gdy nawigacja stoi w karcie (np. `px-3 sm:px-5`). */
  insetClassName?: string;
}

function CountBadge({ count, label }: { count?: number; label?: string }) {
  if (!count) return null;
  return (
    <span
      aria-label={label}
      className="rounded-full bg-primary px-1.5 text-[11px] font-semibold leading-5 text-primary-foreground tabular-nums"
    >
      {count > 99 ? "99+" : count}
    </span>
  );
}

/** Licznik grupy: suma pozycji; nazwa z pozycji, gdy liczy tylko jedna. */
function groupCountLabel(group: SectionNavGroup): string | undefined {
  const counted = group.items.filter((item) => item.count);
  return counted.length === 1 ? counted[0].countLabel : undefined;
}

/**
 * Nawigacja dużego modułu w dwóch poziomach (makieta 18.11.2026): grupy
 * z podkreśleniem, a pod nimi podzakładki aktywnej grupy jako przełącznik.
 * Jeden wzór dla profilu klienta i Finansów — zamiast 15 zakładek w rzędzie,
 * z których część chowała się pod „Więcej” albo za prawą krawędzią.
 * Grupa z jedną pozycją nie pokazuje drugiego paska.
 */
export function SectionNav({
  label,
  groups,
  activeItem,
  onSelect,
  className,
  insetClassName,
}: SectionNavProps) {
  const visible = groups.filter((group) => group.items.length > 0);
  const activeGroup =
    visible.find((group) => group.items.some((item) => item.key === activeItem)) ?? visible[0];
  if (!activeGroup) return null;

  const renderTarget = (
    item: SectionNavItem,
    className: string,
    active: boolean,
    content: ReactNode,
    key: string,
    tourId?: string,
  ) =>
    item.href ? (
      <Link
        key={key}
        href={item.href}
        aria-current={active ? "page" : undefined}
        data-tour={tourId}
        className={className}
      >
        {content}
      </Link>
    ) : (
      <button
        key={key}
        type="button"
        aria-current={active ? "page" : undefined}
        data-tour={tourId}
        onClick={() => onSelect?.(item.key)}
        className={className}
      >
        {content}
      </button>
    );

  return (
    <nav aria-label={label} className={cn("min-w-0", className)}>
      <div
        className={cn(
          "flex min-w-0 gap-0.5 overflow-x-auto border-b border-border",
          insetClassName,
        )}
        style={{ scrollbarWidth: "thin" }}
      >
        {visible.map((group) => {
          const active = group.key === activeGroup.key;
          const first = group.items[0];
          const count = group.items.reduce((sum, item) => sum + (item.count ?? 0), 0);
          return renderTarget(
            first,
            cn(
              "-mb-px inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-[13px] transition-colors pointer-coarse:min-h-10",
              active
                ? "border-primary font-semibold text-foreground"
                : "border-transparent font-medium text-muted-foreground hover:text-foreground",
            ),
            active,
            <>
              {group.label}
              {group.meta ? (
                <span className="text-[11px] font-normal tabular-nums text-muted-foreground">
                  {group.meta}
                </span>
              ) : null}
              <CountBadge count={count} label={groupCountLabel(group)} />
            </>,
            group.key,
            // Grupa z jedną pozycją nie ma drugiego paska — kotwica stoi na grupie.
            group.tourId ?? (group.items.length === 1 ? first.tourId : undefined),
          );
        })}
      </div>
      {activeGroup.items.length > 1 ? (
        <div className={cn("pt-2.5", insetClassName)}>
          <div
            className="inline-flex max-w-full gap-0.5 overflow-x-auto rounded-lg bg-muted/70 p-0.5"
            style={{ scrollbarWidth: "none" }}
          >
            {activeGroup.items.map((item) => {
              const active = item.key === activeItem;
              return renderTarget(
                item,
                cn(
                  "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 py-1 text-[12.5px] font-medium transition-colors pointer-coarse:min-h-9",
                  active
                    ? "bg-card text-foreground shadow-xs ring-1 ring-border/70"
                    : "text-muted-foreground hover:text-foreground",
                ),
                active,
                <>
                  {item.label}
                  <CountBadge count={item.count} label={item.countLabel} />
                </>,
                item.key,
                item.tourId,
              );
            })}
          </div>
        </div>
      ) : null}
    </nav>
  );
}
