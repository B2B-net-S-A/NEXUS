"use client";

import { EquipmentScreen } from "@/components/consultant-portal/PanelScreens";
import { portalApi, portalKeys, usePortalQuery } from "@/lib/api/consultant-portal";

/** Panel konsultanta: Sprzęt. Sesję i wczytanie danych osoby pilnuje układ. */
export default function Page() {
  const me = usePortalQuery(portalKeys.me, portalApi.me);
  return me.data ? <EquipmentScreen me={me.data} /> : null;
}
