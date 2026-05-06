"use client";

import { Search } from "lucide-react";
import { CVDropzoneMatch } from "@/components/sourcing/CVDropzoneMatch";
import { SeekingContractorsBoard } from "@/components/sourcing/SeekingContractorsBoard";

export default function SeekingContractorsPage() {
  return (
    <main className="container mx-auto p-4 max-w-7xl">
      <header className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <div className="bg-purple-100 dark:bg-purple-900/30 p-2 rounded-lg">
            <Search className="w-6 h-6 text-purple-600 dark:text-purple-400" />
          </div>
          <h1 className="text-2xl font-bold text-foreground dark:text-foreground">
            Konsultanci szukający projektu
          </h1>
        </div>
        <p className="text-sm text-muted-foreground dark:text-muted-foreground max-w-3xl">
          Lista konsultantów z kontraktami kończącymi się w najbliższym czasie
          oraz tych, którzy zaznaczyli &ldquo;aktywnie szuka&rdquo; lub &ldquo;otwarty
          na oferty&rdquo;. Dla każdego AI dobiera top dopasowania z otwartych
          rekrutacji. Dodatkowo poniżej możesz wrzucić CV osoby spoza bazy —
          AI dopasuje aktualne projekty bez tworzenia kandydata.
        </p>
      </header>

      <CVDropzoneMatch />

      <SeekingContractorsBoard />
    </main>
  );
}
