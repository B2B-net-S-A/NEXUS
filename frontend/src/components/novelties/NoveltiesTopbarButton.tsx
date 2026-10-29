"use client";

/**
 * ✦ „Nowości” w górnym pasku — nowości mojej roli i co już zaliczyłem.
 * Bez niezaliczonych nowości ikony nie ma (pasek przy 1280 px jest pełny).
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { CheckCircle2, Circle, Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { startNoveltyTour } from "@/components/novelties/NoveltyLayer";
import { useMyNovelties } from "@/lib/novelties/api";
import { pendingCount, type Novelty } from "@/lib/novelties/logic";
import { hasRole, useAuthStore } from "@/store/auth";

const TIER_LABEL: Record<Novelty["tier"], string> = {
  dot: "Drobiazg",
  tour: "Do przeklikania",
  process: "Zmiana procesu",
};

const VIA_LABEL: Record<NonNullable<Novelty["completed_via"]>, string> = {
  tour: "Przeklikane",
  used: "Używasz",
  dot: "Kliknięte",
};

export function NoveltiesTopbarButton() {
  const user = useAuthStore((s) => s.user);
  const hydrated = useAuthStore((s) => s.hydrated);
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const novelties = useMyNovelties(
    hydrated && Boolean(user) && user?.role !== "trainee",
  );
  const pending = pendingCount(novelties);
  if (pending === 0) return null;
  const canSeePanel = hasRole(user, "admin", "head_of_recruitment");

  return (
    <DropdownMenu open={open} onOpenChange={setOpen} modal={false}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-primary hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={`Nowości: ${pending} do przeklikania`}
          title="Nowości"
          data-testid="novelties-topbar"
        >
          <Sparkles className="h-4 w-4" aria-hidden="true" />
          <span className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-primary px-1 text-center text-[10px] font-bold leading-4 text-primary-foreground tabular-nums">
            {pending}
          </span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        className="w-[400px] max-w-[calc(100vw-24px)] p-0"
      >
        <div className="border-b border-border px-4 py-3">
          <p className="text-sm font-semibold">Nowości dla Ciebie</p>
          <p className="text-xs text-muted-foreground">
            Tylko to, co dotyczy Twojej roli. Każda prowadzi na prawdziwy ekran.
          </p>
        </div>
        <ul className="max-h-[360px] divide-y divide-border overflow-y-auto">
          {novelties.map((n) => (
            <li key={n.id} className="flex gap-3 px-4 py-3">
              {n.done ? (
                <CheckCircle2
                  className="mt-0.5 h-4 w-4 shrink-0 text-success"
                  aria-hidden="true"
                />
              ) : (
                <Circle
                  className="mt-0.5 h-4 w-4 shrink-0 text-primary"
                  aria-hidden="true"
                />
              )}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <Badge
                    variant={
                      n.tier === "process"
                        ? "warning"
                        : n.tier === "tour"
                          ? "soft"
                          : "neutral"
                    }
                    size="sm"
                  >
                    {TIER_LABEL[n.tier]}
                  </Badge>
                  <span className="ml-auto text-[11px] text-muted-foreground">
                    {n.done && n.completed_via
                      ? VIA_LABEL[n.completed_via]
                      : "Do zrobienia"}
                  </span>
                </div>
                <p className="mt-1 text-sm font-semibold leading-snug">
                  {n.title}
                </p>
                <p className="text-xs text-muted-foreground">{n.why}</p>
                {!n.done && n.tier !== "dot" ? (
                  <button
                    type="button"
                    className="mt-1.5 text-xs font-semibold text-primary hover:underline"
                    onClick={() => {
                      setOpen(false);
                      startNoveltyTour(n.id);
                      router.push(n.href);
                    }}
                  >
                    Przeklikaj · {n.where} →
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
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
