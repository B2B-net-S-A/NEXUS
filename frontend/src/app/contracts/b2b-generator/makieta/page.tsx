"use client";
// MAKIETA (gałąź claude/contract-module-redesign-f8f030, nie do scalenia): `?w=a|b`.
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { GeneratorA } from "@/components/makiety-kontrakty/pages/GeneratorA";
import { GeneratorB } from "@/components/makiety-kontrakty/pages/GeneratorB";

function Inner() {
  const w = useSearchParams().get("w") === "b" ? "b" : "a";
  return w === "a" ? <GeneratorA /> : <GeneratorB />;
}

export default function MockupPage() {
  return (
    <Suspense fallback={null}>
      <Inner />
    </Suspense>
  );
}
