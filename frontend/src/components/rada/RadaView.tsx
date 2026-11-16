"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { FolderOpen } from "lucide-react";

import { TabbedNav } from "@/components/ds";
import { DocumentsTab } from "./DocumentsTab";

// Zakładki dochodzą etapami (R2 Pulpit, R3 Budżet, R4 Analiza, R5 Posiedzenia).
const TABS = [{ value: "dokumenty", label: "Dokumenty", icon: FolderOpen }];

export function RadaView() {
  const router = useRouter();
  const params = useSearchParams();
  const requested = params.get("tab");
  const tab = TABS.some((t) => t.value === requested) ? (requested as string) : "dokumenty";
  return (
    <div className="mx-auto w-full max-w-[1400px] px-4 py-4 sm:px-6">
      <header className="mb-3">
        <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          Rada nadzorcza
        </p>
        <h1 className="text-xl font-semibold text-foreground">Rada</h1>
      </header>
      <TabbedNav
        tabs={TABS}
        value={tab}
        onValueChange={(v) => router.replace(`/rada?tab=${v}`)}
        ariaLabel="Sekcje Rady"
      >
        <div className="pt-4">{tab === "dokumenty" ? <DocumentsTab /> : null}</div>
      </TabbedNav>
    </div>
  );
}
