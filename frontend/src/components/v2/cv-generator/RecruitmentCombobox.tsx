"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronsUpDown,
  Search,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { type RecruitmentOption, stageLabel } from "@/lib/cv-generator";

type Props = {
  recruitments: RecruitmentOption[];
  /** Selected stage_id as string ("" = nothing selected). */
  value: string;
  onChange: (stageId: string) => void;
  loading?: boolean;
  placeholder?: string;
  /** Shown inside the dropdown when the candidate has no recruitments. */
  emptyText?: string;
};

/**
 * Searchable recruitment picker for the CV generator surfaces.
 *
 * The recruitment list embeds the request number in the title
 * (e.g. "Nordea: … (41166)"), so recruiters need to type that number to find
 * a process — a plain <Select> has no text input. This combobox filters the
 * already-loaded list client-side by title, stage label and job id.
 */
export function RecruitmentCombobox({
  recruitments,
  value,
  onChange,
  loading = false,
  placeholder = "Wybierz rekrutację…",
  emptyText = "Brak procesów rekrutacyjnych dla tego konsultanta.",
}: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const selected = useMemo(
    () => recruitments.find((r) => String(r.stage_id) === value) ?? null,
    [recruitments, value],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return recruitments;
    return recruitments.filter((r) =>
      `${r.job_title} ${stageLabel(r.stage)} ${r.job_id}`
        .toLowerCase()
        .includes(q),
    );
  }, [recruitments, query]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          disabled={loading}
          className="w-full justify-between font-normal"
        >
          {selected ? (
            <span className="flex min-w-0 items-center gap-2 truncate">
              <span className="truncate">{selected.job_title}</span>
              <span className="shrink-0 text-xs text-muted-foreground">
                · {stageLabel(selected.stage)}
              </span>
              <ReadinessChip ready={selected.ready} />
            </span>
          ) : (
            <span className="text-muted-foreground">
              {loading ? "Ładowanie rekrutacji…" : placeholder}
            </span>
          )}
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 text-muted-foreground" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-[--radix-popover-trigger-width] p-0"
      >
        <Command shouldFilter={false}>
          <div className="flex items-center border-b border-border px-3">
            <Search className="mr-2 h-4 w-4 text-muted-foreground" />
            <CommandInput
              placeholder="Szukaj po numerze requestu lub nazwie…"
              value={query}
              onValueChange={setQuery}
              className="h-10 border-0"
            />
          </div>
          <CommandList>
            <CommandEmpty>
              {recruitments.length === 0 ? emptyText : "Brak wyników."}
            </CommandEmpty>
            <CommandGroup>
              {filtered.map((r) => (
                <CommandItem
                  key={r.stage_id}
                  value={String(r.stage_id)}
                  onSelect={() => {
                    onChange(String(r.stage_id));
                    setQuery("");
                    setOpen(false);
                  }}
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="truncate">{r.job_title}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      · {stageLabel(r.stage)}
                    </span>
                    <ReadinessChip ready={r.ready} />
                  </span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

function ReadinessChip({ ready }: { ready: boolean }) {
  return ready ? (
    <CheckCircle2 className="ml-1 h-3.5 w-3.5 shrink-0 text-emerald-600" />
  ) : (
    <AlertTriangle className="ml-1 h-3.5 w-3.5 shrink-0 text-amber-500" />
  );
}
