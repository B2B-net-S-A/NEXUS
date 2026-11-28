"use client";

import { useEffect, useState } from "react";

import { MarketTrainerScreen } from "@/components/consultant-portal/MarketTrainerScreen";
import { TrainerScreen } from "@/components/consultant-portal/PanelScreens";
import { portalKind, type PortalKind } from "@/lib/api/consultant-portal";

/**
 * Panel konsultanta: zgłoszenie trenera (link z zakładki Szkolenia). Trener z rynku
 * (0807) widzi tu dane firmy do umowy. Sesję i wczytanie danych osoby pilnuje układ.
 */
export default function Page() {
  const [kind, setKind] = useState<PortalKind | null>(null);
  useEffect(() => setKind(portalKind()), []);
  if (kind === null) return null;
  return kind === "trainer" ? <MarketTrainerScreen /> : <TrainerScreen />;
}
