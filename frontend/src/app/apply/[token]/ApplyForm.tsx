"use client";

import { useEffect, useRef, useState } from"react";
import { CheckCircle2, Loader2, Paperclip } from"lucide-react";
import { z } from"zod";

import { messageFromApiResponse } from"@/lib/api-error";
import { applyFieldErrors } from"@/lib/apply-form-errors";
import { CONSENT_TEXT } from "@/lib/career/apply";

// UTM query params we forward to the apply endpoint (Traffit gap #4).
// Standard Google Analytics dimensions; backend stores these on the
// CandidateSourceEvent row created at apply time so /reports/sources can
// attribute candidates to channels + campaigns.
const UTM_KEYS = [
  "utm_source",
  "utm_medium",
  "utm_campaign",
  "utm_term",
  "utm_content",
] as const;

interface ApplyFormProps {
 token: string;
 recruiterFirstName: string;
}

const ALLOWED_CV_EXT = [".pdf",".doc",".docx"] as const;
const MAX_CV_BYTES = 10 * 1024 * 1024;

const schema = z.object({
 first_name: z.string().trim().min(1, "Imię jest wymagane").max(100),
 last_name: z.string().trim().min(1, "Nazwisko jest wymagane").max(100),
 email: z.string().trim().email("Nieprawidłowy email"),
 phone: z
 .string()
 .trim()
 .max(30)
 .optional()
 .or(z.literal(""))
 .refine(
 (v) => !v || /^\+?[0-9 ()-]{6,30}$/.test(v), "Nieprawidłowy format telefonu"
 ),
 linkedin: z
 .string()
 .trim()
 .max(500)
 .optional()
 .or(z.literal(""))
 .refine(
 (v) => !v || /^https?:\/\/.+/.test(v), "LinkedIn URL musi zaczynać się od https://"
 ),
 message: z.string().trim().max(2000).optional(),
});

type FieldErrors = Partial<
 Record<keyof z.infer<typeof schema> | "cv" | "consent", string>
>;

const CONSENT_REQUIRED = "Zaznacz zgodę na przetwarzanie danych — bez niej nie możemy przyjąć zgłoszenia.";
type FormStatus ="idle" |"submitting" |"success" |"error";

function apiBase(): string {
 return process.env.NEXT_PUBLIC_API_URL ||"http://localhost:8000";
}

export default function ApplyForm({ token, recruiterFirstName }: ApplyFormProps) {
 const [errors, setErrors] = useState<FieldErrors>({});
 const [submitError, setSubmitError] = useState<string | null>(null);
 const [status, setStatus] = useState<FormStatus>("idle");
 const [cvName, setCvName] = useState<string | null>(null);
 const fileInputRef = useRef<HTMLInputElement | null>(null);

 // Capture UTM query params on mount and stash for the eventual submit.
 // We snapshot once — if the user navigates away and back the URL might
 // have changed; sticking with first-touch matches GA conventions.
 const utmRef = useRef<Record<string, string>>({});
 useEffect(() => {
   const params = new URLSearchParams(window.location.search);
   const captured: Record<string, string> = {};
   for (const key of UTM_KEYS) {
     const v = params.get(key);
     if (v) captured[key] = v.slice(0, 120);
   }
   utmRef.current = captured;
 }, []);

 const validateCv = (file: File | undefined | null): string | null => {
 // Przeglądarka przy braku wyboru wstawia do FormData pusty File bez nazwy.
 if (!file || (!file.name && file.size === 0)) {
 return"Dodaj swoje CV (PDF, DOC lub DOCX).";
 }
 const ext = file.name.toLowerCase().match(/\.[^.]+$/)?.[0] ??"";
 if (!ALLOWED_CV_EXT.includes(ext as (typeof ALLOWED_CV_EXT)[number])) {
 return"CV musi być w formacie PDF, DOC lub DOCX.";
 }
 if (file.size > MAX_CV_BYTES) return"CV jest większe niż 10 MB.";
 return null;
 };

 async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
 e.preventDefault();
 setErrors({});
 setSubmitError(null);

 const form = e.currentTarget;
 const fd = new FormData(form);

 const cvFile = (fd.get("cv") as File | null) ?? null;
 const cvError = validateCv(cvFile);

 const values = {
 first_name: String(fd.get("first_name") ??""),
 last_name: String(fd.get("last_name") ??""),
 email: String(fd.get("email") ??""),
 phone: String(fd.get("phone") ??""),
 linkedin: String(fd.get("linkedin") ??""),
 message: String(fd.get("message") ??""),
 };

 const parsed = schema.safeParse(values);
 const nextErrors: FieldErrors = {};
 if (!parsed.success) {
 for (const issue of parsed.error.issues) {
 const key = issue.path[0] as keyof typeof values;
 nextErrors[key] = issue.message;
 }
 }
 if (cvError) nextErrors.cv = cvError;
 // Zgoda jest wymagana przez API (422 bez niej) — checkbox wysyła `consent=true`.
 if (fd.get("consent") !== "true") nextErrors.consent = CONSENT_REQUIRED;
 if (Object.keys(nextErrors).length > 0) {
 setErrors(nextErrors);
 return;
 }

 // Append UTM params captured on mount (Traffit gap #4 attribution).
 for (const [key, value] of Object.entries(utmRef.current)) {
 fd.append(key, value);
 }

 setStatus("submitting");
 try {
 // Raw fetch — do NOT reuse the internal axios client. This page must
 // not attach the recruiter's Authorization token to a public endpoint.
 const res = await fetch(`${apiBase()}/api/public/apply/${token}`, {
 method: "POST",
 body: fd,
 });
 if (res.status === 201) {
 setStatus("success");
 return;
 }
 if (res.status === 404) {
 setSubmitError("Link wygasł lub został wycofany. Poproś o nowy.");
 setStatus("error");
 return;
 }
 if (res.status === 413) {
 setErrors({ cv: "CV jest większe niż 10 MB." });
 setStatus("idle");
 return;
 }
 if (res.status === 415) {
 setErrors({ cv: "CV musi być w formacie PDF, DOC lub DOCX." });
 setStatus("idle");
 return;
 }
 if (res.status === 429) {
 setSubmitError("Zbyt wiele prób z tego adresu IP. Spróbuj ponownie za kilka minut."
 );
 setStatus("error");
 return;
 }
 const body = await res.json().catch(() => ({}));
 // `detail` z FastAPI NIE jest „na pewno stringiem": dla błędu walidacji
 // `Form(...)` to TABLICA obiektów. Wstawiona wprost do JSX wywracała całą
 // stronę (React #31), a kandydat tracił wypełniony formularz RAZEM
 // z załączonym CV — i nie dowiadywał się, że chodziło o adres e-mail
 // (zod 4 przyjmuje `jan@firma-.pl`, `EmailStr` odrzuca).
 // Odmowa walidacji idzie PRZY POLU: „popraw dane" bez wskazania którego
 // zostawia kandydata z formularzem, którego nie umie poprawić. Realna
 // rozbieżność: zod 4 przyjmuje `jan@firma-.pl`, `EmailStr` odrzuca.
 const fieldErrors = applyFieldErrors(body);
 if (fieldErrors.length > 0) {
 setErrors((prev) => ({
 ...prev,
 ...Object.fromEntries(fieldErrors.map((e) => [e.field, e.message])),
 }));
 setSubmitError("Popraw zaznaczone pola i wyślij ponownie.");
 setStatus("idle");
 return;
 }
 setSubmitError(
 messageFromApiResponse(res.status, body) ??
 "Coś poszło nie tak. Spróbuj ponownie."
 );
 setStatus("error");
 } catch {
 setSubmitError("Brak połączenia. Sprawdź internet i spróbuj ponownie.");
 setStatus("error");
 }
 }

 if (status === "success") {
 return (
 <div className="py-10 text-center space-y-4">
 <div className="mx-auto h-14 w-14 rounded-full bg-primary/10 text-primary flex items-center justify-center">
 <CheckCircle2 className="h-7 w-7" />
 </div>
 <h2 className="font-semibold text-2xl font-extrabold tracking-heading-tight text-foreground">
 Dziękujemy!
 </h2>
 <p className="text-sm text-muted-foreground max-w-sm mx-auto">
 {recruiterFirstName} otrzyma Twoje zgłoszenie i skontaktuje się z Tobą
 najszybciej jak to możliwe.
 </p>
 </div>
 );
 }

 const busy = status === "submitting";

 return (
 <form onSubmit={onSubmit} className="space-y-5" noValidate>
 <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
 <Field label="Imię" error={errors.first_name}>
 <input
 name="first_name"
 autoComplete="given-name"
 disabled={busy}
 className={inputClass}
 required
 />
 </Field>
 <Field label="Nazwisko" error={errors.last_name}>
 <input
 name="last_name"
 autoComplete="family-name"
 disabled={busy}
 className={inputClass}
 required
 />
 </Field>
 </div>

 <Field label="Email" error={errors.email}>
 <input
 name="email"
 type="email"
 autoComplete="email"
 disabled={busy}
 className={inputClass}
 required
 />
 </Field>

 <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
 <Field label="Telefon (opcjonalnie)" error={errors.phone}>
 <input
 name="phone"
 type="tel"
 autoComplete="tel"
 disabled={busy}
 className={inputClass}
 />
 </Field>
 <Field label="LinkedIn (opcjonalnie)" error={errors.linkedin}>
 <input
 name="linkedin"
 type="url"
 placeholder="https://linkedin.com/in/…"
 disabled={busy}
 className={inputClass}
 />
 </Field>
 </div>

 <Field
 label="CV (PDF, DOC lub DOCX, max 10 MB)"
 error={errors.cv}
 >
 <label className="flex items-center justify-between gap-3 rounded-md border border-dashed border-border bg-background/40 px-3 py-2.5 cursor-pointer hover:border-primary">
 <span className="inline-flex items-center gap-2 text-sm">
 <Paperclip className="h-4 w-4 text-muted-foreground" />
 {cvName ??"Wybierz plik…"}
 </span>
 <span className="text-xs text-muted-foreground">
 {cvName ?"Zmień" :"Dodaj"}
 </span>
 <input
 ref={fileInputRef}
 name="cv"
 type="file"
 accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
 disabled={busy}
 className="sr-only"
 onChange={(e) => {
 const f = e.target.files?.[0];
 setCvName(f?.name ?? null);
 const err = validateCv(f);
 setErrors((prev) => ({ ...prev, cv: err ?? undefined }));
 }}
 required
 />
 </label>
 </Field>

 <Field label="Wiadomość (opcjonalnie)" error={errors.message}>
 <textarea
 name="message"
 rows={4}
 disabled={busy}
 className={inputClass}
 maxLength={2000}
 placeholder="Kilka zdań o sobie, motywacji, dostępności…"
 />
 </Field>

 <div className="space-y-1.5">
 <label className="flex items-start gap-3 cursor-pointer">
 <input
 type="checkbox"
 name="consent"
 value="true"
 disabled={busy}
 required
 aria-invalid={errors.consent ? true : undefined}
 className="mt-0.5 h-5 w-5 shrink-0 accent-primary"
 />
 <span className="text-xs leading-relaxed text-muted-foreground">
 {CONSENT_TEXT}{" "}
 <a
 href="/kariera/rodo"
 target="_blank"
 rel="noopener noreferrer"
 className="text-primary underline underline-offset-2"
 >
 Klauzula informacyjna
 </a>
 </span>
 </label>
 {errors.consent && (
 <span className="block text-xs text-destructive">{errors.consent}</span>
 )}
 </div>

 {submitError && (
 <div className="text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md px-3 py-2">
 {submitError}
 </div>
 )}

 <button
 type="submit"
 disabled={busy}
 className="w-full inline-flex items-center justify-center gap-2 rounded-md bg-primary text-white font-semibold text-sm px-4 py-2.5 hover:opacity-90 disabled:opacity-60 disabled:cursor-not-allowed"
 >
 {busy ? (
 <>
 <Loader2 className="h-4 w-4 animate-spin" /> Wysyłanie…
 </>
 ) : ("Wyślij zgłoszenie"
 )}
 </button>
 </form>
 );
}

const inputClass ="w-full rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/30 focus:border-primary disabled:opacity-60";

function Field({
 label,
 error,
 children,
}: {
 label: string;
 error?: string;
 children: React.ReactNode;
}) {
 return (
 <label className="block space-y-1.5">
 <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
 {label}
 </span>
 {children}
 {error && <span className="block text-xs text-destructive">{error}</span>}
 </label>
 );
}
