"use client";

import { Button } from "@/components/ui/button";
import { pageWindow } from "@/lib/page-window";
import { cn } from "@/lib/utils";

interface PageNumberButtonsProps {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  className?: string;
}

/**
 * Numery stron pod listą kandydatów — jak w Traffit (1 2 3 … ostatnia).
 * Bieżąca strona na kolorze `--primary` z `aria-current="page"`. Poniżej `sm`
 * pasek chowa się (zostają „Poprzednia / Następna”), żeby przy 360 px nie
 * było poziomego przewijania.
 */
export function PageNumberButtons({
  page,
  totalPages,
  onPageChange,
  className,
}: PageNumberButtonsProps) {
  const items = pageWindow(page, totalPages);
  if (items.length <= 1) return null;
  return (
    <nav aria-label="Strony wyników" className={cn("hidden items-center gap-1 sm:flex", className)}>
      {items.map((item, index) =>
        item === "gap" ? (
          <span
            key={`gap-${index}`}
            aria-hidden
            className="px-1 text-xs text-muted-foreground"
          >
            …
          </span>
        ) : (
          <Button
            key={item}
            size="icon-sm"
            variant={item === page ? "primary" : "ghost"}
            className="w-auto min-w-8 px-2 tabular-nums"
            aria-label={`Strona ${item}`}
            aria-current={item === page ? "page" : undefined}
            onClick={() => {
              if (item !== page) onPageChange(item);
            }}
          >
            {item}
          </Button>
        ),
      )}
    </nav>
  );
}
