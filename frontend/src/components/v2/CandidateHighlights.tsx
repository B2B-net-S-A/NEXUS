"use client";

import Link from"next/link";
import { AlertTriangle, ExternalLink } from"lucide-react";
import { EmploymentNotice } from"@/components/v2/employment/EmploymentNotice";
import { formatIsoDatePl } from"@/lib/date-pl";
import type { EmploymentMarker } from"@/lib/employment-marker";
import { cn } from"@/lib/utils";
import { hasSectionAccess } from"@/lib/section-access";
import { useAuthStore } from"@/store/auth";

export type EmploymentState =
 |"employed_at_client"
 |"on_bench"
 |"external"
 |"unknown";

export type AvailabilityStatus =
 |"actively_looking"
 |"open_to_offers"
 |"not_looking"
 |"unknown";

export type CandidateStatus ="active" |"passive" |"blacklisted";

export interface EmploymentEngagement {
 client_id: number;
 client_name?: string | null;
 contract_id: number;
 contract_end_date?: string | null;
}

export interface EmploymentInfo {
 state: EmploymentState;
 client_id?: number | null;
 client_name?: string | null;
 contract_id?: number | null;
 job_id?: number | null;
 contract_end_date?: string | null;
 /** Od 17.10.2026 zatrudnienie daje tylko umowa w Kontraktach. */
 source?:"contract" |"none";
 /**
  * Konsolidacja wieloklientowa: WSZYSTKIE aktywne kontrakty (pierwszy = ten
  * sam co pojedyncze pola wyżej). Osoba pracująca u 2 klientów naraz ma tu
  * 2 wpisy — banner pokazuje wtedy komplet („Pracuje u: A, B").
  */
 engagements?: EmploymentEngagement[];
}

export const AVAILABILITY_OPTIONS: { value: AvailabilityStatus; label: string }[] =
 [
 { value: "actively_looking", label: "Aktywnie szuka" },
 { value: "open_to_offers", label: "Otwarty na oferty" },
 { value: "not_looking", label: "Nie szuka" },
 { value: "unknown", label: "Nieznane" },
 ];

/**
 * Full-width banner shown on top of a consultant profile when they're
 * currently employed at one of our clients. Intentionally loud — this is the
 *"do not send profile to the wrong client" guardrail.
 *
 * `compact` (04.10.2026) = ramka w karcie osoby na profilu („Pracuje u nas ·
 * klient · Kontrakt ›”); ta sama treść i to samo ostrzeżenie, bez paska na
 * całą szerokość strony. Szybki podgląd zostaje przy banerze.
 *
 * Od 12.10.2026 ramka rysuje się ze znacznika (`marker`): faza („pracuje”,
 * „kończy”, „zaczyna”), koniec zamówienia i Delivery Lead — ta sama treść co
 * w oknach dodawania do rekrutacji. Bez znacznika (odpowiedź sprzed
 * wdrożenia) zostaje dotychczasowa treść ze starego pola.
 */
export function AtOurClientBanner({
 employment,
 marker,
 className,
 variant ="banner",
}: {
 employment: EmploymentInfo;
 marker?: EmploymentMarker | null;
 className?: string;
 variant?:"banner" |"compact";
}) {
 // Link do kontraktora tylko dla osób z dostępem do sekcji Delivery — bez
 // niego prowadził na 403 (baner i ostrzeżenie zostają dla wszystkich).
 const canOpenContractor = useAuthStore((state) =>
 hasSectionAccess(state.user, "delivery"),
 );
 if (employment.state !== "employed_at_client") return null;
 if (variant ==="compact" && marker) {
 return (
 <EmploymentNotice
 marker={marker}
 tone="neutral"
 role="alert"
 testId="at-our-client-callout"
 className={className}
 />
 );
 }
 // Wieloklientowość: osoba z N równoległymi kontraktami pokazuje KOMPLET
 // klientów („Pracuje u: Bank Pocztowy, VeloBank"), nie tylko ten z najdłuższą
 // umową — inaczej guardrail „nie wysyłaj profilu do złego klienta" milczał
 // o połowie zatrudnień.
 const engagements = employment.engagements ?? [];
 const multi = engagements.length > 1;
 const endText = multi
 ? engagements
 .map(
 (e) =>
 `${e.client_name ?? `Klient #${e.client_id}`}: ${
 e.contract_end_date ? `do ${formatIsoDatePl(e.contract_end_date)}` : "bezterminowo"
 }`,
 )
 .join(" · ")
 : employment.contract_end_date
 ? `Kontrakt do: ${formatIsoDatePl(employment.contract_end_date)}`
 :"Kontrakt bez daty końca";
 const clientLabel = multi
 ? engagements.map((e) => e.client_name ?? `Klient #${e.client_id}`).join(", ")
 : (employment.client_name ??"naszego klienta");
 if (variant ==="compact") {
 return (
 <div
 role="alert"
 data-testid="at-our-client-callout"
 className={cn("rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs", className)}
 >
 <div className="flex items-start justify-between gap-2">
 <p className="flex min-w-0 items-start gap-1.5 font-semibold text-foreground">
 <span aria-hidden="true" className="mt-1 inline-block h-2 w-2 shrink-0 rounded-full bg-success" />
 <span className="min-w-0 break-words">Pracuje u nas · {clientLabel}</span>
 </p>
 {employment.contract_id && canOpenContractor ? (
 <Link
 href={`/contracts/${employment.contract_id}?from=candidate`}
 className="inline-flex min-h-6 shrink-0 items-center font-medium text-primary hover:underline"
 >
 Kontrakt ›
 </Link>
 ) : null}
 </div>
 <p className="mt-0.5 text-muted-foreground">{endText}</p>
 <p className="mt-0.5 font-medium text-warning-muted-foreground">
 Przed wysłaniem profilu zapytaj Delivery.
 </p>
 </div>
 );
 }
 return (
 <div
 role="alert"
 className={cn("rounded-lg border border-primary bg-primary text-primary-foreground shadow-xs","animate-pulse-subtle px-4 py-3",
 className
 )}
 >
 <div className="flex flex-wrap items-start gap-3 sm:flex-nowrap">
 <AlertTriangle className="h-5 w-5 mt-0.5 shrink-0" />
 <div className="flex-1 min-w-0">
 <p className="text-xs font-bold uppercase tracking-[0.12em]">
 {multi ? "Pracuje u" : "Zatrudniony u"}: {clientLabel}
 </p>
 <p className="text-sm text-primary-foreground/90 mt-1">
 {endText} · Nie wysyłaj profilu bez konsultacji z delivery.
 </p>
 </div>
 {employment.contract_id && canOpenContractor ? (
 <Link
 href={`/contracts/${employment.contract_id}?from=candidate`}
 className={cn("inline-flex min-h-11 min-w-11 w-full shrink-0 items-center justify-center gap-1 rounded-md border border-primary-foreground/30 px-3 py-1.5 sm:w-auto",
 "text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary-foreground/10 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-primary-foreground"
 )}
 >
 Przejdź do kontraktora
 <ExternalLink className="h-3.5 w-3.5" />
 </Link>
 ) : null}
 </div>
 </div>
 );
}
