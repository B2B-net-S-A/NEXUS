"use client";

import { useEffect, useState } from"react";
import { Store } from"lucide-react";
import { MarketplaceTable } from"@/components/marketplace/MarketplaceTable";

/**
 * Client-only gate — Next.js 15 + React 19 streaming SSR wiesza hydrację
 * list z React Query. Pierwszy render placeholder, dopiero po mount renderujemy
 * content. Pattern z /app/talents/page.tsx.
 */
export default function MarketplacePage() {
 const [mounted, setMounted] = useState(false);
 useEffect(() => {
 setMounted(true);
 }, []);
 if (!mounted) {
 return (
 <div className="p-8 text-sm text-muted-foreground">
 Ładowanie targu…
 </div>
 );
 }
 return <MarketplacePageContent />;
}

function MarketplacePageContent() {
 return (
 <div className="space-y-6">
 <div>
 <h1 className="text-2xl font-bold text-foreground dark:text-foreground flex items-center gap-2">
 <Store className="w-6 h-6 text-teal-600" />
 Targ kandydatów
 </h1>
 <p className="text-sm text-muted-foreground dark:text-muted-foreground mt-1">
 Kandydaci aktywnie szukający lub świeżo schodzący z projektu. AI
 monitoruje nowe oferty i alertuje o dopasowaniach (score ≥ 70).
 </p>
 </div>
 <MarketplaceTable />
 </div>
 );
}
