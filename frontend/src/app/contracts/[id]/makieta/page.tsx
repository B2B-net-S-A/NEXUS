"use client";
// MAKIETA (gałąź claude/contract-module-redesign-f8f030, nie do scalenia):
// strona kontraktu w dwóch kierunkach — `?w=a|b&tab=…`.
import { Suspense } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { ShellA, TABS_A, type TabKeyA } from "@/components/makiety-kontrakty/shell/ShellA";
import { ShellB, TABS_B, type TabKeyB } from "@/components/makiety-kontrakty/shell/ShellB";
import { TAB_COMPONENTS_A, TAB_COMPONENTS_B } from "@/components/makiety-kontrakty/tabs/registry";

function Inner() {
  const params = useParams<{ id: string }>();
  const sp = useSearchParams();
  const id = Number(params.id);
  const w = sp.get("w") === "b" ? "b" : "a";
  const requested = sp.get("tab") ?? "";
  if (w === "a") {
    const tab = (TABS_A.some((t) => t.key === requested) ? requested : "przeglad") as TabKeyA;
    const Tab = TAB_COMPONENTS_A[tab];
    return (
      <ShellA contractId={id} tab={tab}>
        <Tab contractId={id} />
      </ShellA>
    );
  }
  const tab = (TABS_B.some((t) => t.key === requested) ? requested : "aktywnosc") as TabKeyB;
  const Tab = TAB_COMPONENTS_B[tab];
  return (
    <ShellB contractId={id} tab={tab} expandRates={sp.get("stawki") === "1"}>
      <Tab contractId={id} />
    </ShellB>
  );
}

export default function ContractMockupPage() {
  return (
    <Suspense fallback={null}>
      <Inner />
    </Suspense>
  );
}
