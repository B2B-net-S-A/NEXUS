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
 * podpisane przypisanie załącznika. Dzięki temu `/generate` i dołączenie zgody
 * do gotowego CV mają jeden mechanizm, a obraz nie puchnie w base64 w ciele
 * requestu ani w logach.
 */

import { useEffect, useId, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, Upload, X } from "lucide-react";

import { ConsentCheckNotice } from "@/components/v2/cv/ConsentCheckNotice";
import api from "@/lib/api";
import { needsConsentDecision, type ConsentCheck, type ConsentUploadResult } from "@/lib/consent-check";
import { extractErrorDetail } from "@/lib/cv-generator";
import { cn } from "@/lib/utils";

export const CONSENT_ACCEPT = "image/png,image/jpeg,image/webp";
const MAX_MB = 8;

export interface ConsentContext {
  candidateId?: number;
  stageId?: number;
  clientId?: number | null;
  projectRef?: string;
  bindingStageId?: number;
}

function sameContext(a: ConsentContext, b: ConsentContext) {
  return a.candidateId === b.candidateId && a.stageId === b.stageId &&
    a.clientId === b.clientId && a.projectRef === b.projectRef && a.bindingStageId === b.bindingStageId;
}

interface Props {
  /** Podpisane przypisanie załącznika do źródła i klienta. */
  value: string | null;
  onChange: (consentToken: string | null, filename: string | null) => void;
  context: ConsentContext;
  required: boolean;
  /**
   * Zrzut nie blokuje generacji, ale bez niego pakietu nie da się wysłać
   * klientowi (polityka centralna PKO BP).
   */
  requiredForSending?: boolean;
  disabled?: boolean;
}

export function ConsentScreenshotField({
  value,
  onChange,
  required,
  requiredForSending = false,
  context,
  disabled = false,
}: Props) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // F37 (27.10.2026): wynik sprawdzenia zrzutu; przy niepasującym trzymamy
  // plik, żeby „zapisz mimo to” wysłało go jeszcze raz z powodem.
  const [check, setCheck] = useState<ConsentCheck | null>(null);
  const [mismatchFile, setMismatchFile] = useState<File | null>(null);
  const contextRef = useRef(context);
  contextRef.current = context;
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const requestVersion = useRef(0);
  // Źródło przypisania: osoba + etap albo osoba + klient. Od 13.10.2026 bez
  // pliku z dysku — generator nie ma już ścieżki osoby spoza bazy.
  const hasSubject = !!(context.candidateId && (context.stageId || context.clientId));

  useEffect(() => {
    requestVersion.current += 1;
    setName(null);
    setError(null);
    setCheck(null);
    setMismatchFile(null);
    setBusy(false);
    onChangeRef.current(null, null);
    return () => { requestVersion.current += 1; };
  }, [context.candidateId, context.stageId, context.clientId, context.projectRef, context.bindingStageId]);

  // Wyczyszczenie klucza przez rodzica (np. reset formularza) musi zabrać także
  // nazwę pliku — inaczej pole twierdzi, że coś jest wgrane, choć klucza nie ma.
  useEffect(() => {
    if (!value) setName(null);
  }, [value]);

  const handleFile = async (file: File | undefined, overrideReason?: string) => {
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
      fd.append("candidate_id", String(context.candidateId));
      if (context.stageId) fd.append("stage_id", String(context.stageId));
      if (context.projectRef !== undefined) fd.append("project_ref", context.projectRef);
      if (context.bindingStageId) fd.append("binding_stage_id", String(context.bindingStageId));
      if (context.clientId != null) fd.append("client_id", String(context.clientId));
      if (overrideReason) fd.append("override_reason", overrideReason);
      if (!stillCurrent()) return;
      const res = await api.post<ConsentUploadResult>(
        "/api/cv-generator/consent-screenshot",
        fd,
        // Wspólna instancja axiosa domyślnie wysyła JSON; FormData wymaga
        // jawnego multipart, żeby axios dołożył boundary — inaczej FastAPI
        // nie sparsuje uploadu i zwróci 422.
        { headers: { "Content-Type": "multipart/form-data" }, timeout: 60_000 },
      );
      if (!stillCurrent()) return;
      setCheck(res.data.check ?? null);
      if (needsConsentDecision(res.data)) {
        setMismatchFile(file);
        onChange(null, null);
        return;
      }
      if (!res.data.consent_token) throw new Error("Missing consent binding");
      setMismatchFile(null);
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
    setCheck(null);
    setMismatchFile(null);
    onChange(null, null);
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div className="space-y-1.5" data-testid="consent-screenshot-field">
      <label htmlFor={inputId} className="block text-xs font-medium text-foreground">
        Zrzut zgody kandydata (RODO)
        {required ? (
          <span className="font-normal text-destructive" data-field-mark="required"> * wymagane</span>
        ) : requiredForSending ? (
          <span className="font-normal text-warning-muted-foreground" data-field-mark="sending"> — bez niego CV się nie pobierze</span>
        ) : (
          <span className="font-normal text-muted-foreground" data-field-mark="optional"> (opcjonalnie)</span>
        )}
      </label>
      <p className="text-[11px] text-muted-foreground">
        {required
          ? "Ten klient wymaga zrzutu maila ze zgodą kandydata — trafi automatycznie na koniec CV."
          : requiredForSending
            ? "CV wygenerujesz bez zrzutu, ale nie pobierzesz go, dopóki zrzutu nie dołączysz (możesz też po generacji) — trafi automatycznie na koniec CV."
            : "Jeśli wgrasz, zrzut trafi automatycznie na koniec CV."}
      </p>
      {!hasSubject && <p className="text-[11px] text-muted-foreground">Najpierw wybierz osobę i proces (albo klienta) lub wgraj plik CV.</p>}

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
          {/* Przy niepasującym zrzucie „Wgraj inny zrzut” stoi w uwagach poniżej. */}
          {mismatchFile && !busy ? null : (
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
              {busy ? "Sprawdzam zrzut…" : "Wybierz zrzut (PNG / JPEG)"}
            </label>
          )}
        </div>
      )}

      {value && check?.status === "ok" ? (
        <p className="text-[11px] text-success-muted-foreground" data-testid="consent-check-ok">
          Zgoda pasuje: {check.passed.map((line) => line.detail).join(" · ")}.
        </p>
      ) : value && check?.status === "unavailable" ? (
        <p className="text-[11px] text-muted-foreground" data-testid="consent-check-unavailable">
          AI nie sprawdziło zrzutu — Delivery Lead obejrzy go w QC CV.
        </p>
      ) : null}

      {!value && mismatchFile && check ? (
        <ConsentCheckNotice
          check={check}
          busy={busy}
          onPickAnother={() => inputRef.current?.click()}
          onOverride={(reason) => void handleFile(mismatchFile, reason)}
        />
      ) : null}

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
