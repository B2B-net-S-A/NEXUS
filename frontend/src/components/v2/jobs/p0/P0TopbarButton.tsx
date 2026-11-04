"use client";

import Link from "next/link";
import { Flame } from "lucide-react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useP0Jobs } from "@/lib/api/jobP0";
import { isP0Active } from "@/lib/job-p0";

import { P0Chip } from "./P0Chip";
import { useNow } from "./useNow";

function jobsWord(n: number): string {
  if (n === 1) return "rekrutacja";
  const lastTwo = n % 100;
  const last = n % 10;
  return last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14) ? "rekrutacje" : "rekrutacji";
}

/**
 * „P0 teraz” w górnym pasku (27.10.2026) — na każdym ekranie, u każdego
 * z sekcją Rekrutacje. Bez P0 nie ma przycisku; klik pokazuje listę z powodami.
 */
export function P0TopbarButton() {
  const now = useNow();
  const query = useP0Jobs();
  const items = (query.data?.items ?? []).filter((item) =>
    isP0Active({ is_p0: true, p0_until: item.p0_until }, now),
  );
  if (!query.isSuccess || items.length === 0) return null;
  const label = `P0 teraz: ${items.length} ${jobsWord(items.length)}`;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="hit-area inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg bg-destructive px-2.5 text-xs font-bold text-destructive-foreground hover:bg-destructive/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={label}
          title={label}
          data-testid="p0-topbar-button"
        >
          <Flame className="h-3.5 w-3.5" aria-hidden="true" />
          <span className="flex flex-col text-left leading-tight">
            <span className="hidden text-[10px] font-medium opacity-90 lg:inline">P0 teraz</span>
            <span>
              {items.length}
              <span className="hidden lg:inline"> {jobsWord(items.length)}</span>
            </span>
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[min(24rem,calc(100vw-2rem))] p-2">
        <p className="px-1 pb-1.5 text-sm font-semibold">{label}</p>
        <ul className="grid gap-1.5">
          {items.map((item) => (
            <li key={item.job_id}>
              <Link
                href={`/jobs/${item.job_id}`}
                className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-2 rounded-md bg-destructive-muted p-2 text-xs hover:brightness-95"
              >
                <P0Chip until={item.p0_until} reason={item.p0_reason} />
                <span className="min-w-0">
                  <span className="block truncate font-semibold text-foreground">
                    {item.title}
                    {item.client_name ? (
                      <span className="font-normal text-muted-foreground"> · {item.client_name}</span>
                    ) : null}
                  </span>
                  {item.p0_reason ? (
                    <span className="block break-words text-muted-foreground">„{item.p0_reason}”</span>
                  ) : null}
                </span>
              </Link>
            </li>
          ))}
        </ul>
        <p className="mt-1.5 border-t border-border px-1 pt-1.5 text-xs text-muted-foreground">
          Pasek widzi każdy, na każdym ekranie. Znika, gdy nie ma żadnego P0.
        </p>
      </PopoverContent>
    </Popover>
  );
}
