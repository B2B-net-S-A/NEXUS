"use client";

import { Suspense, useEffect, useState } from "react";
import { ContractsListV2 } from "@/components/v2/pages/ContractsListV2";

export default function ContractsPage() {
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    console.log("[ContractsPage] mounted");
    const handler = (e: ErrorEvent) => {
      console.error("[ContractsPage] error:", e.message, e.error);
      setErr(e.message + " — " + (e.error?.stack?.slice(0, 300) || ""));
    };
    window.addEventListener("error", handler);
    return () => window.removeEventListener("error", handler);
  }, []);

  return (
    <>
      {err && (
        <pre className="text-xs bg-red-100 text-red-900 p-3 rounded whitespace-pre-wrap">
          {err}
        </pre>
      )}
      <Suspense fallback={<div className="p-8 text-sm text-gray-500">Ładowanie listy kontraktów…</div>}>
        <ContractsListV2 />
      </Suspense>
    </>
  );
}
