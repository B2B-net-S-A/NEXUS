"use client";

/**
 * Nazwa pliku CV do klienta z „Zmień nazwę” — bez pobierania i wgrywania od nowa.
 * Rozszerzenie zostaje .docx, a znaki niedozwolone w nazwie pliku odpadają na serwerze.
 */

import { useEffect, useId, useState } from "react";
import { Pencil, RotateCcw } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { candidateStageCvApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";

const stem = (name: string): string => name.replace(/\.docx$/i, "");

interface CvFileNameRowProps {
  stageId: number;
  filename: string;
  /** Nazwa ze wzoru klienta; jest tylko po ręcznej zmianie i pozwala do niej wrócić. */
  patternFilename?: string | null;
  readOnly?: boolean;
}

export function CvFileNameRow({ stageId, filename, patternFilename, readOnly }: CvFileNameRowProps) {
  const { showSuccess, showError } = useToast();
  const [current, setCurrent] = useState(filename);
  const [pattern, setPattern] = useState(patternFilename ?? null);
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(stem(filename));
  const [saving, setSaving] = useState(false);
  const inputId = useId();

  // Nowa wersja CV i odświeżenie karty przynoszą nazwę z serwera.
  useEffect(() => {
    setCurrent(filename);
    setPattern(patternFilename ?? null);
  }, [filename, patternFilename]);

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await candidateStageCvApi.branded.rename(stageId, `${value.trim()}.docx`);
      setCurrent(data.filename);
      setPattern(data.pattern_filename ?? null);
      setOpen(false);
      showSuccess("Zmieniono nazwę pliku CV.");
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zmienić nazwy pliku."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <p data-testid="cv-file-name" className="flex flex-wrap items-center gap-x-1.5 [overflow-wrap:anywhere]">
      <span>
        Plik: <span className="font-medium text-foreground">{current}</span>
      </span>
      {readOnly ? null : (
        <button
          type="button"
          data-tour="cv.file-name"
          className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
          onClick={() => {
            setValue(stem(current));
            setOpen(true);
          }}
        >
          <Pencil className="h-3 w-3" aria-hidden /> Zmień nazwę
        </button>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Zmień nazwę pliku CV</DialogTitle>
            <DialogDescription>
              Pod tą nazwą pobierzesz CV i wyślesz je klientowi. Treść CV się nie zmienia.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 px-6 py-4 text-sm">
            <div className="space-y-1">
              <label htmlFor={inputId} className="block text-xs font-medium text-muted-foreground">
                Nazwa pliku
              </label>
              <span className="flex items-center gap-1.5">
                <Input id={inputId} value={value} maxLength={194} onChange={(event) => setValue(event.target.value)} />
                <span className="text-muted-foreground">.docx</span>
              </span>
            </div>
            {pattern && pattern !== current ? (
              <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground [overflow-wrap:anywhere]">
                Ze wzoru klienta: {pattern}
                <button
                  type="button"
                  className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
                  onClick={() => setValue(stem(pattern))}
                >
                  <RotateCcw className="h-3 w-3" aria-hidden /> Wróć do wzoru
                </button>
              </p>
            ) : null}
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Anuluj
            </Button>
            <Button onClick={() => void save()} loading={saving} disabled={!value.trim()}>
              Zapisz nazwę
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </p>
  );
}
