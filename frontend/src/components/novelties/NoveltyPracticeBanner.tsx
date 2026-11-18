"use client";

// Pasek nad ekranem w trakcie przeklikania nowości z porcji dnia (18.11.2026).
// Tryb Poligonu: prawdziwe ekrany, rekrutacja ćwiczebna, zapisy wyłączone.

import { Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { DAILY_PATH } from "@/lib/novelties/daily";
import { writeTour } from "@/lib/novelties/logic";
import { leavePoligon } from "@/lib/poligon/mode";

export function NoveltyPracticeBanner() {
  return (
    <div
      role="status"
      className="sticky top-0 z-30 -mx-4 -mt-4 mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-primary/30 bg-primary/10 px-4 py-2 text-sm text-foreground md:-mx-6 md:-mt-6 md:mb-6 md:px-6"
      data-testid="novelty-practice-banner"
    >
      <Sparkles className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
      <span className="min-w-0 flex-1">
        <b className="font-semibold">Nowości na dziś</b> · ćwiczysz na rekrutacji ćwiczebnej — kliknięcia niczego nie zapisują
      </span>
      <Button
        size="sm"
        variant="outline"
        onClick={() => {
          writeTour(null);
          leavePoligon(DAILY_PATH);
        }}
      >
        Wróć do listy
      </Button>
    </div>
  );
}
