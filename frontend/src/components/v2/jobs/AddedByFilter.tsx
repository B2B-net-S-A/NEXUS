"use client";

/**
 * Filtr „Kto dodał” Tablicy rekrutacji (14.10.2026, D2): jeden przycisk
 * w nagłówku rekrutacji, nie pasek filtrów (ten zdjęliśmy 02.10.2026). To samo
 * menu otwiera etykieta kolejki w panelu osoby, bo w widoku „Rozwiń” Tablica
 * jest zasłonięta. Logika i napisy: `lib/board-added-by.ts`.
 */
import { ChevronDown, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  ADDED_BY_ALL,
  addedByChoiceLabel,
  addedByKey,
  type AddedByFilter,
  type AddedByOption,
} from "@/lib/board-added-by";
import { cn } from "@/lib/utils";

export interface AddedByMenuProps {
  options: readonly AddedByOption[];
  value: AddedByFilter;
  onChange: (filter: AddedByFilter) => void;
}

/** Treść menu (wewnątrz `DropdownMenu`) — wspólna dla nagłówka i panelu osoby. */
export function AddedByMenuContent({
  options,
  value,
  onChange,
  align = "end",
}: AddedByMenuProps & { align?: "start" | "end" }) {
  const selectedKey = addedByKey(value);
  const top = options.filter((o) => o.key === "all" || o.isViewer);
  const others = options.filter((o) => o.key !== "all" && o.key !== "none" && !o.isViewer);
  const withoutAdder = options.find((o) => o.key === "none");
  const item = (option: AddedByOption) => (
    <DropdownMenuRadioItem
      key={option.key}
      value={option.key}
      // „Ty” z zerem zostaje w menu (wiadomo, że to nie błąd), ale wybrać
      // nie ma czego — chyba że już jest wybrane.
      disabled={option.count === 0 && option.key !== selectedKey}
      data-testid={`added-by-option-${option.key}`}
    >
      <span className="min-w-0 flex-1 truncate">{option.label}</span>
      <span className="ml-3 shrink-0 tabular-nums text-muted-foreground">{option.count}</span>
    </DropdownMenuRadioItem>
  );
  return (
    <DropdownMenuContent
      align={align}
      className="w-72"
      data-testid="added-by-menu"
      data-tour="jobs.board.added-by-menu"
    >
      <DropdownMenuLabel>Kto dodał osobę do tej rekrutacji</DropdownMenuLabel>
      <p className="px-2 pb-1.5 text-xs text-muted-foreground">
        Jak na karcie: kto wziął „Biorę”, a bez tego kto dodał. Liczby: osoby w toku na Tablicy.
      </p>
      <DropdownMenuRadioGroup
        value={selectedKey}
        onValueChange={(key) => {
          const option = options.find((o) => o.key === key);
          if (option) onChange(option.filter);
        }}
      >
        {top.map(item)}
        {others.length > 0 ? <DropdownMenuSeparator /> : null}
        {others.map(item)}
        {withoutAdder ? <DropdownMenuSeparator /> : null}
        {withoutAdder ? item(withoutAdder) : null}
      </DropdownMenuRadioGroup>
    </DropdownMenuContent>
  );
}

/** Przycisk w nagłówku rekrutacji: „Kto dodał: wszyscy ▾” / „Kto dodał: Ty · 23 z 66” + „✕”. */
export function AddedByFilterButton({ options, value, onChange }: AddedByMenuProps) {
  const active = value.kind !== "all";
  const choice = addedByChoiceLabel(value, options);
  const total = options.find((o) => o.key === "all")?.count ?? 0;
  const visible = options.find((o) => o.key === addedByKey(value))?.count ?? 0;
  return (
    <div className="inline-flex items-center gap-1" data-testid="added-by-filter">
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className={cn("gap-1.5", active && "border-primary/40 bg-primary/10")}
            aria-label={
              active ? `Kto dodał: ${choice}. Widać ${visible} z ${total} osób.` : `Kto dodał: ${choice}`
            }
            data-testid="added-by-trigger"
            data-tour="jobs.board.added-by"
          >
            <span className="font-normal text-muted-foreground">Kto dodał:</span>
            <span className="font-semibold">{choice}</span>
            {active ? (
              <span className="font-normal tabular-nums text-muted-foreground">
                · {visible} z {total}
              </span>
            ) : null}
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
          </Button>
        </DropdownMenuTrigger>
        <AddedByMenuContent options={options} value={value} onChange={onChange} />
      </DropdownMenu>
      {active ? (
        <Button
          type="button"
          size="icon-sm"
          variant="ghost"
          onClick={() => onChange(ADDED_BY_ALL)}
          aria-label="Pokaż wszystkich (wyłącz filtr „Kto dodał”)"
          data-testid="added-by-clear"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </Button>
      ) : null}
    </div>
  );
}
