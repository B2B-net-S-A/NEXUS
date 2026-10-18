"use client";

import { useState } from "react";
import { FileArchive } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadHrFile } from "@/lib/api/hr";
import { paymentPaths, useSymfoniaPreview } from "@/lib/api/hr-payments";
import { formatMoney } from "@/lib/money";
import { resolveViewState } from "@/lib/view-state";

import { symfoniaFileLabel } from "./payments-format";

interface SymfoniaExportButtonProps {
  year: number;
  month: number;
  /** Paczka powstaje z zamkniętego miesiąca (zamrożone kwoty). */
  closed: boolean;
}

/**
 * „Eksport do Symfonii” w ekranie miesiąca Płac (R5): podgląd paczki
 * (pliki, sumy, lista rzeczy do zrobienia ręcznie) i pobranie ZIP-a.
 * Kwoty dostają Płace, plik nieobecności — Kadry (rodzaj nieobecności, D6).
 */
export function SymfoniaExportButton({ year, month, closed }: SymfoniaExportButtonProps) {
  const [open, setOpen] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const preview = useSymfoniaPreview(year, month, open);
  const { showToast } = useToast();
  const state = resolveViewState({
    isLoading: preview.isLoading,
    isError: preview.isError,
    error: preview.error,
    isSuccess: preview.isSuccess,
  });

  const download = async () => {
    setDownloading(true);
    try {
      await downloadHrFile(
        paymentPaths.symfoniaZip(year, month),
        `symfonia-${year}-${String(month).padStart(2, "0")}.zip`,
      );
      setOpen(false);
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się pobrać paczki."), "error");
    } finally {
      setDownloading(false);
    }
  };

  const data = preview.data;
  return (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={() => setOpen(true)}
        disabled={!closed}
        title={
          closed
            ? "Paczka plików do importu w Symfonii: nieobecności, premie, zlecenia, zestawienie."
            : "Paczka dla Symfonii powstaje z zamkniętego miesiąca."
        }
      >
        <FileArchive className="h-4 w-4" aria-hidden />
        Eksport do Symfonii
      </Button>
      {open ? (
        <AppModal
          open={open}
          onOpenChange={setOpen}
          size="lg"
          title={`Paczka dla Symfonii${data ? ` · ${data.label}` : ""}`}
          description="Pliki importujesz w Symfonii: Firma › Import zdarzeń i Firma › Import › danych z Excela. Instrukcja jest w zestawieniu PDF."
          footer={
            <>
              <Button variant="ghost" onClick={() => setOpen(false)}>
                Wróć
              </Button>
              <Button onClick={download} disabled={state !== "ready" || downloading}>
                {downloading ? "Pobieranie…" : "Pobierz paczkę (ZIP)"}
              </Button>
            </>
          }
        >
          {state === "loading" ? (
            <p className="text-sm text-muted-foreground">Przygotowanie podglądu…</p>
          ) : state !== "ready" || !data ? (
            <p role="alert" className="text-sm text-destructive">
              {apiErrorMessage(preview.error, "Nie udało się przygotować paczki.")}
            </p>
          ) : (
            <div className="space-y-4 text-sm">
              <div>
                <h3 className="font-medium text-foreground">Pliki</h3>
                <ul className="mt-1 space-y-0.5">
                  {data.files.map((file) => (
                    <li key={file.name} className="flex justify-between gap-3">
                      <span>{symfoniaFileLabel(file.name)}</span>
                      <span className="text-muted-foreground">
                        {file.rows === null ? file.name : `${file.rows} wierszy`}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
              {data.totals && Object.keys(data.totals).length > 0 ? (
                <div>
                  <h3 className="font-medium text-foreground">Sumy kontrolne</h3>
                  <ul className="mt-1 space-y-0.5">
                    {Object.entries(data.totals).map(([label, value]) => (
                      <li key={label} className="flex justify-between gap-3">
                        <span>{label}</span>
                        <span className="tabular-nums">{formatMoney(value, "PLN")}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <div>
                <h3 className="font-medium text-foreground">
                  Do zrobienia ręcznie ({data.todo.length})
                </h3>
                {data.todo.length === 0 ? (
                  <p className="text-muted-foreground">Nic — wszyscy mają identyfikator z Symfonii.</p>
                ) : (
                  <ul className="mt-1 list-disc space-y-0.5 pl-5">
                    {data.todo.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                )}
              </div>
              {data.notes.length > 0 ? (
                <ul className="space-y-0.5 text-xs text-muted-foreground">
                  {data.notes.map((note) => (
                    <li key={note}>{note}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          )}
        </AppModal>
      ) : null}
    </>
  );
}
