"use client";

import { useState } from "react";
import { FileText } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { costPdfPath } from "@/lib/api/finance-ledger";
import { openAuthenticatedFile } from "@/lib/authenticated-files";

interface CostPdfButtonProps {
  entryId: number;
  invoiceNumber: string | null;
  /** `icon` = sama ikona w wierszu kolejki, `full` = przycisk z napisem na karcie. */
  look?: "icon" | "full";
}

/**
 * „Podgląd PDF” faktury z kolejki kosztów: z KSeF — wizualizacja XML-a
 * (backend pobiera go przy pierwszym otwarciu), spoza KSeF — wgrany PDF.
 * Te same bramki co karta (D2: faktury osób zespołu tylko Płace i admin).
 */
export function CostPdfButton({ entryId, invoiceNumber, look = "full" }: CostPdfButtonProps) {
  const { showToast } = useToast();
  const [busy, setBusy] = useState(false);
  const label = `Podgląd PDF faktury ${invoiceNumber ?? `#${entryId}`}`;
  const open = async () => {
    setBusy(true);
    try {
      await openAuthenticatedFile(costPdfPath(entryId), "application/pdf", `faktura-${entryId}.pdf`);
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się otworzyć podglądu PDF."), "error");
    } finally {
      setBusy(false);
    }
  };
  if (look === "icon") {
    return (
      <Button
        size="icon-sm"
        variant="ghost"
        aria-label={label}
        title="Podgląd PDF"
        data-tour="finance.cost-pdf"
        loading={busy}
        onClick={() => void open()}
      >
        {busy ? null : <FileText className="h-4 w-4" aria-hidden />}
      </Button>
    );
  }
  return (
    <Button
      size="sm"
      variant="outline"
      aria-label={label}
      loading={busy}
      data-tour="finance.cost-pdf"
      onClick={() => void open()}
    >
      {busy ? null : <FileText className="h-4 w-4" aria-hidden />}
      Podgląd PDF
    </Button>
  );
}

export default CostPdfButton;
