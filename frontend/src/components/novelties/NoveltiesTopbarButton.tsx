"use client";

/**
 * ✦ „Nowości” w górnym pasku — archiwum (decyzja Artura 18.11.2026).
 * Nowe funkcje przeklikuje się rano w porcji dnia (`/nowosci-dnia`), więc tu
 * nie ma licznika ani kropki. W środku: 3 najważniejsze z tygodnia, drobiazgi
 * jedną linią, wcześniejsze tygodnie zwinięte. Przeklikanie z archiwum idzie
 * tak samo jak rano — na Poligonie.
 */

import Link from "next/link";
import { useMemo, useState } from "react";
import { ChevronRight, Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { startNoveltyPractice } from "@/components/novelties/NoveltyLayer";
import { useMyNovelties } from "@/lib/novelties/api";
import type { Novelty } from "@/lib/novelties/logic";
import { noveltyWeeks } from "@/lib/novelties/weekly";
import { hasRole, useAuthStore } from "@/store/auth";

function HeadlineItem({
  novelty,
  onGo,
}: {
  novelty: Novelty;
  onGo: (n: Novelty) => void;
}) {
  return (
    <li className="px-4 py-2.5">
      <div className="flex items-center gap-2">
        {novelty.tier === "process" ? (
          <Badge variant="warning" size="sm">
            Zmiana sposobu pracy
          </Badge>
        ) : null}
        <p className="min-w-0 flex-1 text-sm font-semibold leading-snug">
          {novelty.title}
        </p>
      </div>
      <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
        {novelty.why}
      </p>
      <button
        type="button"
        className="mt-1 text-xs font-semibold text-primary hover:underline"
        onClick={() => onGo(novelty)}
      >
        Pokaż mi · {novelty.where.split(" → ")[0]} →
      </button>
    </li>
  );
}

export function NoveltiesTopbarButton() {
  const user = useAuthStore((s) => s.user);
  const hydrated = useAuthStore((s) => s.hydrated);
  const [open, setOpen] = useState(false);
  const [showRest, setShowRest] = useState(false);
  const [expandedWeek, setExpandedWeek] = useState<string | null>(null);
  const novelties = useMyNovelties(
    hydrated && Boolean(user) && user?.role !== "trainee",
  );
  const weeks = useMemo(() => noveltyWeeks(novelties), [novelties]);
  const current = weeks[0];

  if (!current) return null;
  const canSeePanel = hasRole(user, "admin", "head_of_recruitment");

  const go = (n: Novelty) => {
    setOpen(false);
    startNoveltyPractice(n);
  };

  return (
    <DropdownMenu
      open={open}
      onOpenChange={setOpen}
      modal={false}
    >
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-primary hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Nowości — archiwum"
          title="Nowości"
          data-testid="novelties-topbar"
        >
          <Sparkles className="h-4 w-4" aria-hidden="true" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        className="w-[400px] max-w-[calc(100vw-24px)] p-0"
      >
        <div className="border-b border-border px-4 py-3">
          <p className="text-sm font-semibold">
            Nowości · tydzień {current.label}
          </p>
          <p className="text-xs text-muted-foreground">
            Archiwum. Nowe przeklikujesz rano, przy pierwszym wejściu dnia.
          </p>
        </div>
        <div className="max-h-[420px] overflow-y-auto">
          <p className="px-4 pt-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Najważniejsze
          </p>
          <ul className="divide-y divide-border">
            {current.headlines.map((n) => (
              <HeadlineItem key={n.id} novelty={n} onGo={go} />
            ))}
          </ul>
          {current.rest.length > 0 ? (
            <div className="border-t border-border px-4 py-2">
              <button
                type="button"
                className="flex w-full items-center gap-1 text-left text-xs font-semibold text-muted-foreground hover:text-foreground"
                onClick={() => setShowRest((v) => !v)}
              >
                <ChevronRight
                  className={`h-3.5 w-3.5 transition-transform ${showRest ? "rotate-90" : ""}`}
                  aria-hidden="true"
                />
                Drobiazgi z tego tygodnia ({current.rest.length})
              </button>
              {showRest ? (
                <ul className="mt-1 space-y-1 pl-5">
                  {current.rest.map((n) => (
                    <li key={n.id} className="text-xs">
                      <button
                        type="button"
                        className="text-left hover:underline"
                        onClick={() => go(n)}
                      >
                        {n.title}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
          <div className="border-t border-border px-4 py-2">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Wcześniej
            </p>
            <ul className="mt-1">
              {weeks.slice(1, 6).map((w) => {
                const items = [...w.headlines, ...w.rest];
                const expanded = expandedWeek === w.monday;
                return (
                  <li key={w.monday}>
                    <button
                      type="button"
                      className="flex w-full items-center gap-1 py-1 text-left text-xs hover:text-primary"
                      onClick={() =>
                        setExpandedWeek(expanded ? null : w.monday)
                      }
                    >
                      <ChevronRight
                        className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${expanded ? "rotate-90" : ""}`}
                        aria-hidden="true"
                      />
                      <span className="font-medium">Tydzień {w.label}</span>
                      <span className="ml-auto text-muted-foreground tabular-nums">
                        {items.length}
                      </span>
                    </button>
                    {expanded ? (
                      <ul className="mb-1 space-y-1 pl-5">
                        {items.map((n) => (
                          <li key={n.id} className="text-xs">
                            <button
                              type="button"
                              className="text-left hover:underline"
                              onClick={() => go(n)}
                            >
                              {n.title}
                            </button>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
        {canSeePanel ? (
          <div className="border-t border-border px-4 py-2.5 text-right text-xs">
            <Link
              href="/settings/nowosci"
              className="font-semibold text-primary hover:underline"
              onClick={() => setOpen(false)}
            >
              Kto już umie →
            </Link>
          </div>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
