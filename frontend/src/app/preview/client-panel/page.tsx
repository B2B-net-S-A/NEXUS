"use client";

/**
 * Harness panelu klienta: prawdziwe komponenty, dane fikcyjne, zero zapytań.
 *
 * - `?c=fikc-anna` — od razu ta osoba,
 * - `?rate=0` / `?actions=0` / `?others=0` — wyłączniki z NEXUSA,
 * - `?nocv=1` — bez pliku CV,
 * - `?state=gone|expired|error` — ekrany błędów,
 * - `?manage=1` — okno „Panel klienta” Delivery Leada.
 */

import { Suspense, useMemo } from "react";
import { useSearchParams } from "next/navigation";

import { ClientPanelApp } from "@/components/v2/client-panel/ClientPanelApp";
import { ClientPanelSlideOver } from "@/components/v2/recruitment/slideovers/ClientPanelSlideOver";
import type { PanelTransport } from "@/lib/api/clientPanel";

import { fictionalAdminTransport, fictionalPanelTransport } from "./fixtures";

const FAILURE_STATUS: Record<string, number> = { gone: 404, expired: 410, error: 503 };

function Harness() {
  const params = useSearchParams();
  const manage = params.get("manage") === "1";
  const state = params.get("state");
  const key = params.toString();
  const transport = useMemo<PanelTransport>(() => {
    const base = fictionalPanelTransport({
      showRate: params.get("rate") !== "0",
      allowActions: params.get("actions") !== "0",
      showOthers: params.get("others") !== "0",
      withCv: params.get("nocv") !== "1",
    });
    const status = state ? FAILURE_STATUS[state] : undefined;
    if (!status) return base;
    return {
      ...base,
      fetchPanel: () =>
        Promise.reject(Object.assign(new Error("harness"), { response: { status } })),
    };
    // Parametry w adresie są stałe przez życie tego ekranu; `key` obejmuje wszystkie.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  const adminTransport = useMemo(() => fictionalAdminTransport(), []);

  if (manage) {
    return <ClientPanelSlideOver open onOpenChange={() => undefined} jobId={1} transport={adminTransport} />;
  }
  return (
    <ClientPanelApp
      token={`harness-${key}`}
      initialPublicId={params.get("c")}
      transport={transport}
    />
  );
}

export default function ClientPanelPreviewPage() {
  return (
    <Suspense fallback={null}>
      <Harness />
    </Suspense>
  );
}
