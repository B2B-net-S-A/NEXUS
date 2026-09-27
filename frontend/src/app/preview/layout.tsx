"use client";

import { useEffect, type ReactNode } from "react";

import {
  activatePreviewNetworkGuard,
  deactivatePreviewNetworkGuard,
} from "./preview-network-guard";

/**
 * Wspólny layout harnessów `/preview/*` (runda 10, R10-N10-2): żaden harness
 * nie wyśle zapisu do API i nie użyje tokenu oglądającego.
 *
 * Blokada włącza się JUŻ W RENDERZE — efekty dzieci biegną przed efektem
 * rodzica, a harnessy odpalają zapytania w swoich `useEffect`. Efekt tylko
 * pilnuje wyłączenia po wyjściu z `/preview` (i ponownego włączenia w
 * StrictMode, który montuje efekty dwa razy).
 */
export default function PreviewLayout({ children }: { children: ReactNode }) {
  activatePreviewNetworkGuard();
  useEffect(() => {
    activatePreviewNetworkGuard();
    return deactivatePreviewNetworkGuard;
  }, []);
  return <>{children}</>;
}
