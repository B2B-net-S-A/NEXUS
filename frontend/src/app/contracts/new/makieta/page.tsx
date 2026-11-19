"use client";
// MAKIETA (gałąź claude/contract-module-redesign-f8f030, nie do scalenia): `?w=a|b`.
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { NewA } from "@/components/makiety-kontrakty/pages/NewA";
import { NewB } from "@/components/makiety-kontrakty/pages/NewB";

function Inner() {
  const w = useSearchParams().get("w") === "b" ? "b" : "a";
  return w === "a" ? <NewA /> : <NewB />;
}

export default function MockupPage() {
  return (
    <Suspense fallback={null}>
      <Inner />
    </Suspense>
  );
}
