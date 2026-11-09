"use client";

import { HelpScreen } from "@/components/consultant-portal/PanelScreens";
import { portalApi, portalKeys, usePortalQuery } from "@/lib/api/consultant-portal";

/** Panel konsultanta: Pomoc. Sesję i wczytanie danych osoby pilnuje układ. */
export default function Page() {
  const me = usePortalQuery(portalKeys.me, portalApi.me);
  return me.data ? <HelpScreen me={me.data} /> : null;
}
