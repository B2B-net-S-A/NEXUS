"use client";

// Okno pobrania oryginału CV po złym wyniku generatora (decyzja Artura 02.11.2026):
// osoba z samą rolą rekrutera podaje, co generator zrobił źle. Zasady i powody:
// `lib/cv-download-access.ts`, zestawienie: Ustawienia → „Jakość generatora CV”.

import { useState } from "react";
import { Download } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadBlob } from "@/lib/authenticated-files";
import {
  CV_FEEDBACK_REASONS,
  downloadOriginalAfterGenerator,
  type CvFeedbackReason,
} from "@/lib/cv-download-access";

export function CvDownloadExceptionDialog({
  stageId,
  open,
  onOpenChange,
}: {
  stageId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { showError, showSuccess } = useToast();
  const [reasons, setReasons] = useState<CvFeedbackReason[]>([]);
  const [detail, setDetail] = useState("");
  const [busy, setBusy] = useState(false);
  const otherPicked = reasons.includes("other");
  const blocked = reasons.length === 0 || (otherPicked && detail.trim().length === 0);

  const toggle = (code: CvFeedbackReason) =>
    setReasons((current) =>
      current.includes(code) ? current.filter((item) => item !== code) : [...current, code],
    );

  const submit = async () => {
    setBusy(true);
    try {
      const { blob, filename } = await downloadOriginalAfterGenerator(stageId, { reasons, detail });
      downloadBlob(blob, filename ?? "CV");
      showSuccess("Pobrano oryginał CV. Dziękujemy za uwagi do generatora.");
      setReasons([]);
      setDetail("");
      onOpenChange(false);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się pobrać oryginału CV."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Co generator zrobił źle?</DialogTitle>
          <DialogDescription>
            Po odpowiedzi pobierzesz oryginał CV tej osoby. Odpowiedź trafia do poprawy generatora.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-2">
          {CV_FEEDBACK_REASONS.map((item) => (
            <label key={item.code} className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={reasons.includes(item.code)}
                onChange={() => toggle(item.code)}
              />
              {item.label}
            </label>
          ))}
          <textarea
            value={detail}
            onChange={(event) => setDetail(event.target.value)}
            rows={2}
            maxLength={1000}
            aria-label="Przykład z tego CV"
            placeholder={otherPicked ? "Opisz, co poszło nie tak" : "Przykład z tego CV (opcjonalnie)"}
            className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          />
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button type="button" disabled={blocked} loading={busy} onClick={() => void submit()}>
            <Download className="h-3.5 w-3.5" aria-hidden />
            Pobierz oryginał
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
