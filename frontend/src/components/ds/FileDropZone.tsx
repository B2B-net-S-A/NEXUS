"use client";

import { useRef, useState } from "react";
import type { DragEvent } from "react";
import { Upload } from "lucide-react";

import { cn } from "@/lib/utils";

export interface FileDropZoneProps {
  /** Wybrany plik (kontrolowane z zewnątrz — komponent nie trzyma stanu pliku). */
  file: File | null;
  onPick: (file: File | null) => void;
  /** Lista rozszerzeń dla `accept` ORAZ dla walidacji po upuszczeniu. */
  accept: string;
  /** Limit rozmiaru; `0` = bez limitu. */
  maxBytes?: number;
  label: string;
  hint?: string;
  /** Komunikat błędu walidacji — podawany przez rodzica, żeby błąd zapisu
   *  i błąd wyboru pliku wyświetlały się w jednym miejscu. */
  error?: string | null;
  onError?: (message: string) => void;
  disabled?: boolean;
  inputId: string;
  className?: string;
}

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
}

/**
 * Pole pliku z obsługą „przeciągnij i upuść".
 *
 * Powstało, bo w repo było SZEŚĆ niezależnych implementacji drag&drop i zero
 * wspólnego komponentu — a pola PDF w modalach zamówień od dawna WYGLĄDAŁY jak
 * dropzone (`border-dashed`), nie będąc nim.
 *
 * Dwie własności, których nie wolno tu zgubić:
 *
 * 1. **Walidacja jest ta sama dla obu dróg dodania.** Upuszczenie pliku omija
 *    atrybut `accept` przeglądarki, więc bez jawnego sprawdzenia rozszerzenia
 *    i rozmiaru drag&drop byłby furtką na to, czego okno wyboru nie przepuści.
 * 2. **Dodanie pliku niczego nie uruchamia.** Komponent wyłącznie oddaje plik
 *    rodzicowi; odczyt danych z dokumentu jest osobną, świadomą akcją
 *    użytkownika (wymóg ticketu).
 */
export function FileDropZone({
  file,
  onPick,
  accept,
  maxBytes = 0,
  label,
  hint,
  error,
  onError,
  disabled = false,
  inputId,
  className,
}: FileDropZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const allowed = accept
    .split(",")
    .map((ext) => ext.trim().toLowerCase())
    .filter((ext) => ext.startsWith("."));

  function validate(candidate: File): string | null {
    if (allowed.length > 0 && !allowed.includes(extensionOf(candidate.name))) {
      return `Dozwolone formaty: ${allowed.join(", ")}`;
    }
    if (maxBytes > 0 && candidate.size > maxBytes) {
      return `Plik przekracza ${Math.round(maxBytes / (1024 * 1024))} MB`;
    }
    return null;
  }

  function pick(candidate: File | null) {
    if (!candidate) {
      onPick(null);
      return;
    }
    const problem = validate(candidate);
    if (problem) {
      onError?.(problem);
      // Reset inputa: bez tego wybranie TEGO SAMEGO pliku po poprawce nie
      // odpali `onChange` i użytkownik widzi martwy formularz.
      if (inputRef.current) inputRef.current.value = "";
      return;
    }
    onPick(candidate);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragOver(false);
    if (disabled) return;
    pick(event.dataTransfer.files?.[0] ?? null);
  }

  return (
    <div className={className}>
      {/* Widoczny obszar to <label htmlFor>, nie div z role="button".
          Powód nie jest stylistyczny: etykieta wiąże tekst z prawdziwą
          kontrolką pliku, więc czytnik ekranu ogłasza pole poprawnie,
          kliknięcie otwiera okno wyboru NATYWNIE (bez JS), a testy i
          automatyzacja trafiają w input przez jego nazwę. Wersja z divem
          zrywała to powiązanie i `getByLabelText` przestawał znajdować pole. */}
      <label
        htmlFor={inputId}
        data-testid={`dropzone-${inputId}`}
        data-drag-over={dragOver ? "true" : "false"}
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={cn(
          "flex cursor-pointer items-center gap-3 rounded-lg border-2 border-dashed px-4 py-3 transition-colors",
          disabled && "cursor-not-allowed opacity-60",
          dragOver
            ? "border-primary bg-primary/10"
            : "border-border bg-muted/40 hover:bg-muted/60",
        )}
      >
        <Upload className="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden />
        <div className="min-w-0">
          <div className="text-sm font-semibold">{label}</div>
          <div className="truncate text-xs text-muted-foreground">
            {file
              ? `${file.name} · ${(file.size / 1024).toFixed(0)} KB`
              : (hint ??
                `${accept} · przeciągnij plik tutaj lub wybierz z dysku`)}
          </div>
        </div>
      </label>
      <input
        ref={inputRef}
        id={inputId}
        type="file"
        accept={accept}
        disabled={disabled}
        className="sr-only"
        onChange={(event) => pick(event.target.files?.[0] ?? null)}
      />
      {error ? (
        <p className="mt-1 text-xs text-destructive" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
