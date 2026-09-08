"use client";

/**
 * Zrzut ekranu ze zgodą kandydata — pole w generatorze CV.
 *
 * Wymóg PKO BP: pod treścią CV ma być widoczny zrzut maila, w którym kandydat
 * zgadza się na przetwarzanie danych przez bank. Do 09.2026 generator tylko
 * OSTRZEGAŁ rekrutera, żeby wkleił go ręcznie przed wysyłką — bo nie miał skąd
 * wziąć obrazu. To pole zamyka tę lukę.
 *
 * Plik idzie do magazynu obiektów OSOBNYM żądaniem, a do generacji trafia sam
 * klucz. Dzięki temu obie ścieżki generacji — JSON-owa `/generate` i multipart
 * `/generate-upload` — mają jeden mechanizm, a obraz nie puchnie w base64
 * w ciele requestu ani w logach.
 */

import { useEffect, useId, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, Upload, X } from "lucide-react";

import api from "@/lib/api";
import { extractErrorDetail } from "@/lib/cv-generator";
import { cn } from "@/lib/utils";

export const CONSENT_ACCEPT = "image/png,image/jpeg,image/webp";
const MAX_MB = 8;

interface Props {
  /** Klucz w magazynie — `null` dopóki nic nie wgrano. */
  value: string | null;
  onChange: (storageKey: string | null, filename: string | null) => void;
  required: boolean;
  disabled?: boolean;
}

export function ConsentScreenshotField({
  value,
  onChange,
  required,
  disabled = false,
}: Props) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Wyczyszczenie klucza przez rodzica (np. reset formularza) musi zabrać także
  // nazwę pliku — inaczej pole twierdzi, że coś jest wgrane, choć klucza nie ma.
  useEffect(() => {
    if (!value) setName(null);
  }, [value]);

  const handleFile = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    if (file.size > MAX_MB * 1024 * 1024) {
      setError(`Zrzut jest za duży (limit ${MAX_MB} MB).`);
      return;
    }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await api.post<{ storage_key: string; filename: string }>(
        "/api/cv-generator/consent-screenshot",
        fd,
        // Wspólna instancja axiosa domyślnie wysyła JSON; FormData wymaga
        // jawnego multipart, żeby axios dołożył boundary — inaczej FastAPI
        // nie sparsuje uploadu i zwróci 422.
        { headers: { "Content-Type": "multipart/form-data" }, timeout: 60_000 },
      );
      setName(res.data.filename || file.name);
      onChange(res.data.storage_key, res.data.filename || file.name);
    } catch (err) {
      const detail = await extractErrorDetail(err);
      setError(detail || "Nie udało się wgrać zrzutu.");
      onChange(null, null);
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const clear = () => {
    setName(null);
    setError(null);
    onChange(null, null);
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div className="space-y-1.5" data-testid="consent-screenshot-field">
      <label htmlFor={inputId} className="block text-xs font-medium text-foreground">
        Zrzut zgody kandydata (RODO)
        {required && <span className="text-destructive"> *</span>}
      </label>
      <p className="text-[11px] text-muted-foreground">
        {required
          ? "Ten klient wymaga zrzutu maila ze zgodą kandydata — trafi automatycznie na koniec CV."
          : "Opcjonalnie — jeśli wgrasz, zrzut trafi automatycznie na koniec CV."}
      </p>

      {value ? (
        <div
          className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1.5 text-xs text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-200"
          data-testid="consent-screenshot-attached"
        >
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          <span className="truncate">{name || "Zrzut wgrany"}</span>
          {!disabled && (
            <button
              type="button"
              onClick={clear}
              className="ml-auto rounded p-0.5 hover:bg-emerald-100 dark:hover:bg-emerald-900"
              aria-label="Usuń zrzut"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      ) : (
        // Keep the absolute sr-only input in the form's scroll container, too.
        <div className="relative flex items-center gap-2">
          <input
            ref={inputRef}
            id={inputId}
            type="file"
            accept={CONSENT_ACCEPT}
            disabled={disabled || busy}
            onChange={(e) => void handleFile(e.target.files?.[0])}
            className="sr-only"
          />
          <label
            htmlFor={inputId}
            className={cn(
              "inline-flex cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium",
              "border-border bg-card hover:bg-muted",
              (disabled || busy) && "pointer-events-none opacity-60",
              required && !value && "border-destructive/40",
            )}
          >
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Upload className="h-3.5 w-3.5" />
            )}
            {busy ? "Wgrywam…" : "Wybierz zrzut (PNG / JPEG)"}
          </label>
        </div>
      )}

      {error && (
        <p
          className="inline-flex items-center gap-1.5 text-[11px] text-destructive"
          role="alert"
        >
          <AlertTriangle className="h-3.5 w-3.5" />
          {error}
        </p>
      )}
    </div>
  );
}
