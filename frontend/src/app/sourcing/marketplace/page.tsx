"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Search, Store, UploadCloud } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CVDropzoneMatch } from "@/components/sourcing/CVDropzoneMatch";
import { SeekingContractorsBoard } from "@/components/sourcing/SeekingContractorsBoard";
import { MarketplaceTable } from "@/components/marketplace/MarketplaceTable";
import { useMarketplaceThreshold } from "@/hooks/useMarketplaceThreshold";

type TabKey = "snapshot" | "manual" | "cv";

const VALID_TABS: ReadonlySet<TabKey> = new Set(["snapshot", "manual", "cv"]);

function MarketplacePageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tabParam = searchParams.get("tab");
  const initialTab: TabKey = VALID_TABS.has(tabParam as TabKey)
    ? (tabParam as TabKey)
    : "snapshot";

  const [tab, setTab] = useState<TabKey>(initialTab);
  const threshold = useMarketplaceThreshold();

  const handleTabChange = (next: string) => {
    const nextTab = next as TabKey;
    setTab(nextTab);
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", nextTab);
    router.replace(`/sourcing/marketplace?${params.toString()}`, {
      scroll: false,
    });
  };

  return (
    <main className="container mx-auto p-4 max-w-7xl">
      <header className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <div className="bg-teal-100 dark:bg-teal-900/30 p-2 rounded-lg">
            <Store className="w-6 h-6 text-teal-600 dark:text-teal-400" />
          </div>
          <h1 className="text-2xl font-bold text-foreground dark:text-foreground">
            Targ / Dostępni konsultanci
          </h1>
        </div>
        <p className="text-sm text-muted-foreground dark:text-muted-foreground max-w-3xl">
          Wszyscy konsultanci dostępni do nowego projektu w jednym miejscu —
          z kończącymi się kontraktami, deklaracją „aktywnie szuka" lub
          ręcznie wystawieni na targ. AI dobiera top dopasowania do otwartych
          rekrutacji i alertuje gdy pojawia się świeży job.
        </p>
      </header>

      <Tabs value={tab} onValueChange={handleTabChange} className="space-y-4">
        <TabsList>
          <TabsTrigger value="snapshot">
            <Search className="h-3.5 w-3.5" />
            Szukają projektu
          </TabsTrigger>
          <TabsTrigger value="manual">
            <Store className="h-3.5 w-3.5" />
            Targ ręczny
          </TabsTrigger>
          <TabsTrigger value="cv">
            <UploadCloud className="h-3.5 w-3.5" />
            Match CV (spoza bazy)
          </TabsTrigger>
        </TabsList>

        <TabsContent value="snapshot" className="space-y-4">
          <p className="text-sm text-muted-foreground max-w-3xl">
            Konsultanci z kontraktami kończącymi się w wybranym horyzoncie
            oraz tacy, którzy zaznaczyli „aktywnie szuka" lub „otwarty na
            oferty". Dla każdego AI dobiera top dopasowania z otwartych
            rekrutacji.
          </p>
          <SeekingContractorsBoard />
        </TabsContent>

        <TabsContent value="manual" className="space-y-4">
          <p className="text-sm text-muted-foreground max-w-3xl">
            Kandydaci ręcznie wystawieni na targ na określony czas (TTL).
            Tło: kiedy edytujesz lub dodajesz nowy job, system automatycznie
            skanuje tę listę i alertuje o dopasowaniach ze score ≥ {threshold}.
          </p>
          <MarketplaceTable
            sourceEvent="manual"
            emptyHint='Nikogo nie wystawiono na targ ręcznie. Wejdź na profil kandydata i kliknij „Wrzuć na targ", żeby pokazać go tu na 30 dni (lub własny okres).'
          />
        </TabsContent>

        <TabsContent value="cv" className="space-y-4">
          <p className="text-sm text-muted-foreground max-w-3xl">
            Wrzuć CV osoby spoza bazy — AI dopasuje aktualne otwarte
            rekrutacje bez tworzenia kandydata. One-off check.
          </p>
          <CVDropzoneMatch />
        </TabsContent>
      </Tabs>
    </main>
  );
}

export default function MarketplacePage() {
  return (
    <Suspense
      fallback={
        <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>
      }
    >
      <MarketplacePageContent />
    </Suspense>
  );
}
