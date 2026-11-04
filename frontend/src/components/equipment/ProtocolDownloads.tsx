"use client";

import { useState } from "react";
import { FileDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadProtocolDocument, type EquipmentProtocol } from "@/lib/api/equipment";

/** Pobranie protokołu jako Word albo PDF (PDF bywa chwilowo niedostępny — 503). */
export function ProtocolDownloads({
  protocol,
}: {
  protocol: Pick<EquipmentProtocol, "id" | "number">;
}) {
  const [busy, setBusy] = useState<"docx" | "pdf" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const download = async (format: "docx" | "pdf") => {
    setBusy(format);
    setError(null);
    try {
      await downloadProtocolDocument(protocol, format);
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się pobrać protokołu."));
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" disabled={busy !== null} onClick={() => download("pdf")}>
          <FileDown className="h-4 w-4" aria-hidden />
          {busy === "pdf" ? "Pobieranie…" : "Pobierz PDF"}
        </Button>
        <Button variant="outline" size="sm" disabled={busy !== null} onClick={() => download("docx")}>
          <FileDown className="h-4 w-4" aria-hidden />
          {busy === "docx" ? "Pobieranie…" : "Pobierz Word"}
        </Button>
      </div>
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
