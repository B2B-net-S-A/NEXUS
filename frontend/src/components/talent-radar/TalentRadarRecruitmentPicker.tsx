"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BriefcaseBusiness, Check, ChevronsUpDown } from "lucide-react";

import api from "@/lib/api";
import { foldText } from "@/lib/contract-client-filter";
import type { TalentRadarRecruitmentRef } from "@/lib/talent-radar-recruitment";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

interface JobsListItem {
  id: number;
  title: string;
  client_id: number | null;
  client_name: string | null;
}

interface JobsListResponse {
  items: JobsListItem[];
}

interface Props {
  value: TalentRadarRecruitmentRef | null;
  onChange: (recruitment: TalentRadarRecruitmentRef) => void;
}

/**
 * Jedna otwarta rekrutacja jest kontekstem całego wyszukiwania: jej klient
 * zasila filtr dopuszczalności, a jej id jest celem akcji „Przypisz”. Dzięki
 * temu karta kandydata nie musi po kliknięciu pytać po raz drugi „dokąd?”.
 */
export function TalentRadarRecruitmentPicker({ value, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const recruitmentsQuery = useQuery({
    queryKey: ["talent-radar", "open-recruitments"],
    queryFn: async () => {
      const { data } = await api.get<JobsListResponse>("/api/jobs", {
        params: { open_only: true, page_size: 100, sort: "newest" },
      });
      return data.items
        .filter(
          (job): job is JobsListItem & { client_id: number } =>
            typeof job.client_id === "number",
        )
        .map((job) => ({
          id: job.id,
          title: job.title,
          clientId: job.client_id,
          clientName: job.client_name?.trim() || `Klient #${job.client_id}`,
        }));
    },
    staleTime: 60_000,
  });

  const filtered = useMemo(() => {
    const recruitments = recruitmentsQuery.data ?? [];
    const folded = foldText(query.trim());
    if (!folded) return recruitments;
    return recruitments.filter((recruitment) =>
      foldText(
        `${recruitment.title} ${recruitment.clientName} ${recruitment.id}`,
      ).includes(folded),
    );
  }, [query, recruitmentsQuery.data]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id="tr-recruitment"
          type="button"
          role="combobox"
          aria-expanded={open}
          aria-label={
            value
              ? `Rekrutacja: ${value.title}, ${value.clientName}`
              : "Wybierz rekrutację"
          }
          variant="outline"
          className="w-full justify-between font-normal"
        >
          <span className="flex min-w-0 items-center gap-2">
            <BriefcaseBusiness
              className={cn(
                "h-4 w-4 shrink-0",
                value ? "text-primary" : "text-muted-foreground",
              )}
            />
            <span
              className={cn(
                "truncate",
                !value && "text-muted-foreground",
              )}
            >
              {value
                ? `${value.title} · ${value.clientName}`
                : "Wybierz rekrutację…"}
            </span>
          </span>
          <ChevronsUpDown className="h-4 w-4 shrink-0 text-muted-foreground" />
        </Button>
      </PopoverTrigger>

      <PopoverContent
        align="start"
        className="w-(--radix-popover-trigger-width) p-0"
      >
        <Command shouldFilter={false}>
          <CommandInput
            placeholder="Szukaj po nazwie, kliencie lub ID…"
            value={query}
            onValueChange={setQuery}
          />
          <CommandList>
            {recruitmentsQuery.isLoading ? (
              <div className="p-3 text-sm text-muted-foreground">
                Ładowanie rekrutacji…
              </div>
            ) : recruitmentsQuery.isError ? (
              <div className="flex flex-col gap-2 p-3">
                <p className="text-sm text-destructive">
                  Nie udało się załadować rekrutacji.
                </p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => recruitmentsQuery.refetch()}
                >
                  Spróbuj ponownie
                </Button>
              </div>
            ) : (
              <CommandEmpty>Brak otwartych rekrutacji.</CommandEmpty>
            )}
            <CommandGroup>
              {filtered.map((recruitment) => (
                <CommandItem
                  key={recruitment.id}
                  value={String(recruitment.id)}
                  onSelect={() => {
                    onChange(recruitment);
                    setQuery("");
                    setOpen(false);
                  }}
                >
                  <Check
                    className={cn(
                      "mr-2 h-4 w-4 shrink-0",
                      value?.id === recruitment.id
                        ? "opacity-100"
                        : "opacity-0",
                    )}
                  />
                  <span className="flex min-w-0 flex-col">
                    <span className="truncate">{recruitment.title}</span>
                    <span className="truncate text-xs text-muted-foreground">
                      {recruitment.clientName} · #{recruitment.id}
                    </span>
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
