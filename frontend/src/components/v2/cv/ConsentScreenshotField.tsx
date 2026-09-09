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
 * podpisane przypisanie załącznika. Dzięki temu obie ścieżki generacji — JSON-owa `/generate` i multipart
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

export interface ConsentContext {
  candidateId?: number;
  stageId?: number;
  clientId?: number | null;
  cvFile?: File | null;
}

function sameContext(a: ConsentContext, b: ConsentContext) {
  return a.candidateId === b.candidateId && a.stageId === b.stageId &&
    a.clientId === b.clientId && a.cvFile === b.cvFile;
}

interface Props {
  /** Podpisane przypisanie załącznika do źródła i klienta. */
  value: string | null;
  onChange: (consentToken: string | null, filename: string | null) => void;
  context: ConsentContext;
  required: boolean;
  disabled?: boolean;
}

export function ConsentScreenshotField({
  value,
  onChange,
  required,
  context,
  disabled = false,
}: Props) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const contextRef = useRef(context);
  contextRef.current = context;
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const requestVersion = useRef(0);
  const hasSubject = !!context.cvFile || !!(context.candidateId && context.stageId);

  useEffect(() => {
    requestVersion.current += 1;
    setName(null);
    setError(null);
    setBusy(false);
    onChangeRef.current(null, null);
    return () => { requestVersion.current += 1; };
  }, [context.candidateId, context.stageId, context.clientId, context.cvFile]);

  // Wyczyszczenie klucza przez rodzica (np. reset formularza) musi zabrać także
  // nazwę pliku — inaczej pole twierdzi, że coś jest wgrane, choć klucza nie ma.
  useEffect(() => {
    if (!value) setName(null);
  }, [value]);

  const handleFile = async (file: File | undefined) => {
    if (!file || !hasSubject || disabled) return;
    const submittedContext = context;
    const version = ++requestVersion.current;
    const stillCurrent = () => version === requestVersion.current && sameContext(submittedContext, contextRef.current);
    setError(null);
    if (file.size > MAX_MB * 1024 * 1024) {
      setError(`Zrzut jest za duży (limit ${MAX_MB} MB).`);
      return;
    }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (context.cvFile) {
        const digest = await crypto.subtle.digest("SHA-256", await context.cvFile.arrayBuffer());
        fd.append("cv_sha256", Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join(""));
      } else {
        fd.append("candidate_id", String(context.candidateId));
        fd.append("stage_id", String(context.stageId));
      }
      if (context.clientId != null) fd.append("client_id", String(context.clientId));
      if (!stillCurrent()) return;
      const res = await api.post<{ consent_token: string; filename: string }>(
        "/api/cv-generator/consent-screenshot",
        fd,
        // Wspólna instancja axiosa domyślnie wysyła JSON; FormData wymaga
        // jawnego multipart, żeby axios dołożył boundary — inaczej FastAPI
        // nie sparsuje uploadu i zwróci 422.
        { headers: { "Content-Type": "multipart/form-data" }, timeout: 60_000 },
      );
      if (!stillCurrent()) return;
      if (!res.data.consent_token) throw new Error("Missing consent binding");
      setName(res.data.filename || file.name);
      onChange(res.data.consent_token, res.data.filename || file.name);
    } catch (err) {
      const detail = await extractErrorDetail(err);
      if (!stillCurrent()) return;
      setError(detail || "Nie udało się wgrać zrzutu.");
      onChange(null, null);
    } finally {
      if (stillCurrent()) {
        setBusy(false);
        if (inputRef.current) inputRef.current.value = "";
      }
    }
  };

  const clear = () => {
    requestVersion.current += 1;
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
      {!hasSubject && <p className="text-[11px] text-muted-foreground">Najpierw wybierz osobę i rekrutację albo wgraj plik CV.</p>}

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
            disabled={disabled || busy || !hasSubject}
            onChange={(e) => void handleFile(e.target.files?.[0])}
            className="sr-only"
          />
          <label
            htmlFor={inputId}
            className={cn(
              "inline-flex cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium",
              "border-border bg-card hover:bg-muted",
              (disabled || busy || !hasSubject) && "pointer-events-none opacity-60",
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
