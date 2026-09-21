"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { BarChart3, Briefcase, Trophy } from "lucide-react";
import { cn } from "@/lib/utils";
import { RywalizacjaChapter } from "@/components/insights/chapters/RywalizacjaChapter";
import { WynikiChapter } from "@/components/insights/chapters/WynikiChapter";
import { KlienciChapter } from "@/components/insights/chapters/KlienciChapter";

export type ChapterId = "rywalizacja" | "wyniki" | "klienci";

/**
 * Rozdziały zakładki Body Leasing (21.09.2026).
 *
 * Zastępują dawne zakładki Rekrutacja i Delivery Lead: 17 sekcji na dwóch
 * długich stronach dzielimy na trzy rozdziały, z których widać jeden naraz.
 * Kolejność = kolejność pytań zespołu: kto wygrywa → jak idzie → u kogo.
 */
export const CHAPTERS: {
  id: ChapterId;
  label: string;
  lede: string;
  icon: React.ComponentType<{ className?: string }>;
}[] = [
  {
    id: "rywalizacja",
    label: "Rywalizacja",
    lede: "Kampania, Liga Mistrzów, wyścigi miesiąca i ścieżka rozwoju.",
    icon: Trophy,
  },
  {
    id: "wyniki",
    label: "Wyniki",
    lede: "Aktywność, lejek, zespół, praca w toku i dopływ kandydatów.",
    icon: BarChart3,
  },
  {
    id: "klienci",
    label: "Klienci",
    lede: "Portfele Delivery Leadów: klienci, hit ratio i uwagi.",
    icon: Briefcase,
  },
];

export const DEFAULT_CHAPTER: ChapterId = "rywalizacja";

export function isChapterId(v: string | null): v is ChapterId {
  return v === "rywalizacja" || v === "wyniki" || v === "klienci";
}

export function BodyLeasingPanel() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const raw = searchParams.get("ch");
  const active: ChapterId = isChapterId(raw) ? raw : DEFAULT_CHAPTER;
  const current = CHAPTERS.find((c) => c.id === active) ?? CHAPTERS[0];

  const select = (next: ChapterId) => {
    // Okres NIE przechodzi między rozdziałami: każdy ma inny domyślny
    // (Wyniki — miesiąc, Klienci — rok), więc przeniesiony wybór udawałby
    // decyzję, której nikt w tym rozdziale nie podjął.
    const params = new URLSearchParams();
    params.set("tab", "body-leasing");
    params.set("ch", next);
    router.push(`/insights?${params.toString()}`, { scroll: false });
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <nav
          aria-label="Rozdziały Body Leasing"
          className="inline-flex gap-0.5 rounded-lg bg-muted p-1"
        >
          {CHAPTERS.map((chapter) => {
            const Icon = chapter.icon;
            const on = chapter.id === active;
            return (
              <button
                key={chapter.id}
                type="button"
                onClick={() => select(chapter.id)}
                aria-current={on ? "page" : undefined}
                className={cn(
                  "inline-flex min-h-9 items-center gap-2 rounded-md px-4 text-sm font-semibold transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
                  on
                    ? "bg-card text-foreground shadow-xs"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <Icon className="h-4 w-4" />
                {chapter.label}
              </button>
            );
          })}
        </nav>
        <p className="text-sm text-muted-foreground">{current.lede}</p>
      </div>

      {active === "rywalizacja" && <RywalizacjaChapter />}
      {active === "wyniki" && <WynikiChapter />}
      {active === "klienci" && <KlienciChapter />}
    </div>
  );
}
