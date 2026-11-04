"use client";

import { useState } from "react";
import { ChevronDown, History } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { readRecentSearches, type RecentSearch } from "@/lib/search-memory";
import { useAuthStore } from "@/store/auth";

function whenLabel(at: number, now = Date.now()): string {
  const date = new Date(at);
  const time = date.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });
  const today = new Date(now);
  const yesterday = new Date(now - 24 * 60 * 60 * 1000);
  if (date.toDateString() === today.toDateString()) return `dziś ${time}`;
  if (date.toDateString() === yesterday.toDateString()) return `wczoraj ${time}`;
  return date.toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit" }) + ` ${time}`;
}

/**
 * „Ostatnie wyszukiwania” — 10 ostatnich w tej przeglądarce (`search-memory`),
 * obok zapisanych wyszukiwań z alertem, nie zamiast nich. Lista czytana przy
 * otwarciu menu, więc zawsze świeża.
 */
export function RecentSearchesMenu({
  kind,
  jobId = null,
  onPick,
}: {
  kind: RecentSearch["kind"];
  jobId?: number | null;
  onPick: (entry: RecentSearch) => void;
}) {
  const userId = useAuthStore((s) => s.user?.id ?? null);
  const [entries, setEntries] = useState<RecentSearch[]>([]);
  return (
    <DropdownMenu
      modal={false}
      onOpenChange={(open) => {
        if (!open) return;
        setEntries(
          readRecentSearches(userId).filter(
            (r) => r.kind === kind && (kind === "list" || r.jobId === jobId),
          ),
        );
      }}
    >
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="md">
          <History className="h-4 w-4" aria-hidden />
          Ostatnie wyszukiwania
          <ChevronDown className="h-3.5 w-3.5 opacity-60" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[min(26rem,calc(100vw-2rem))]">
        <DropdownMenuLabel>Twoje ostatnie wyszukiwania</DropdownMenuLabel>
        {entries.length === 0 ? (
          <p className="px-2 py-3 text-sm text-muted-foreground">
            Jeszcze nic tu nie ma. Wyszukiwanie trafia na listę po kliknięciu „Szukaj”.
          </p>
        ) : (
          entries.map((entry) => (
            <DropdownMenuItem
              key={`${entry.at}-${entry.query}`}
              onSelect={() => onPick(entry)}
              className="flex flex-col items-start gap-0.5"
            >
              <span className="line-clamp-2 text-sm font-medium text-foreground">{entry.label}</span>
              <span className="text-xs text-muted-foreground">{whenLabel(entry.at)}</span>
            </DropdownMenuItem>
          ))
        )}
        <DropdownMenuSeparator />
        <p className="px-2 py-1.5 text-xs text-muted-foreground">
          Pamiętamy 10 ostatnich, tylko w tej przeglądarce. Wyszukiwania z alertem zapisujesz w „Zapisane”.
        </p>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
