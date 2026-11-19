"use client";
// MAKIETA (gałąź claude/contract-module-redesign-f8f030, nie do scalenia):
// lista kontraktów `?w=a|b&widok=aktywne|konczace&contract=<id>`.
import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ListDetailLayout } from "@/components/ds/ListDetailLayout";
import { ListA } from "@/components/makiety-kontrakty/list/ListA";
import { ListB } from "@/components/makiety-kontrakty/list/ListB";
import { EndingA } from "@/components/makiety-kontrakty/list/EndingA";
import { EndingB } from "@/components/makiety-kontrakty/list/EndingB";
import { PanelA } from "@/components/makiety-kontrakty/list/PanelA";
import { PanelB } from "@/components/makiety-kontrakty/list/PanelB";
import { listHref, type ListView } from "@/components/makiety-kontrakty/list/ListParts";

function Inner() {
  const sp = useSearchParams();
  const router = useRouter();
  const w = sp.get("w") === "b" ? "b" : "a";
  const view: ListView = sp.get("widok") === "konczace" ? "konczace" : "aktywne";
  const selected = sp.get("contract") ? Number(sp.get("contract")) : null;
  const close = () => router.replace(listHref(w, view));
  const list =
    view === "aktywne"
      ? w === "a"
        ? <ListA selected={selected} />
        : <ListB selected={selected} />
      : w === "a"
        ? <EndingA selected={selected} />
        : <EndingB selected={selected} />;
  const panel = selected
    ? w === "a"
      ? <PanelA contractId={selected} onClose={close} />
      : <PanelB contractId={selected} onClose={close} />
    : null;
  return <ListDetailLayout list={list} panel={panel} onClose={close} panelLabel="Podgląd kontraktu" />;
}

export default function ContractsListMockupPage() {
  return (
    <Suspense fallback={null}>
      <Inner />
    </Suspense>
  );
}
