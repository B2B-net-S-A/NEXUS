"use client";

// Pasek nad ekranem w trakcie lekcji nowości (18.11.2026, lekcje od 23.11.2026).
// Tryb Poligonu: prawdziwe ekrany, dane ćwiczebne, zapisy wyłączone.

import { Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { DAILY_PATH } from "@/lib/novelties/daily";
import { leaveLesson, readRun } from "@/lib/novelties/lessons";
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
        <b className="font-semibold">Lekcja na Poligonie</b> · prawdziwe ekrany, ćwiczebne dane — nic się nie zapisze naprawdę
      </span>
      <Button
        size="sm"
        variant="outline"
        onClick={() => {
          const run = readRun();
          if (run) {
            leaveLesson(run);
            return;
          }
          writeTour(null);
          leavePoligon(DAILY_PATH);
        }}
      >
        Wróć do listy
      </Button>
    </div>
  );
}
