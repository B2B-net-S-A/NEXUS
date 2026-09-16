"use client";

import Link from "next/link";

import { cn } from "@/lib/utils";

/**
 * Adres strony konkretnego kontraktu — nagłówek „Kontrakt #NNN", domyślna
 * zakładka „Szczegóły".
 *
 * Świadomie NIE przez `buildContractDetailHref` z `lib/contracts-list-navigation`:
 * tamten helper dokleja `returnTo`, walidowane do ścieżek `/contracts`, więc
 * adres profilu klienta zostałby po cichu zamieniony na rejestr kontraktów —
 * przycisk powrotu na stronie kontraktu kłamałby o tym, skąd przyszedł
 * użytkownik. Powrót z listy zamówień obsługuje przycisk wstecz przeglądarki
 * (`/clients/{id}?tab=zamowienia` jest w adresie).
 */
export function contractDetailHref(contractId: number): string {
  return `/contracts/${contractId}`;
}

interface Props {
  /** Kontrakt Z TEGO WIERSZA — nie „jakiś kontrakt tej osoby". */
  contractId: number;
  name: string;
  className?: string;
}

/**
 * Imię i nazwisko konsultanta na liście zamówień jako link do JEGO kontraktu
 * u TEGO klienta. Jedno źródło adresu i wyglądu dla czterech miejsc, w których
 * nazwisko pada w wierszu zamówienia (kafelek kontraktora, wiersz przyszłego
 * zamówienia, linia karty grupy, linia przyszła karty grupy).
 *
 * Kolor tekstu zostaje dziedziczony: lista bywa kilkudziesięciowierszowa,
 * a ściana nazwisk w kolorze brandu czyta się gorzej niż sama afordancja
 * hover/focus.
 *
 * BEZ `title` i bez `aria-label`: nazwa dostępna linku ma być nazwiskiem.
 * Zmierzone w przeglądarce (nie założone): `<a title="…">Nazwisko</a>` trafia
 * do drzewa dostępności jako link o nazwie z `title` — samo nazwisko znika,
 * więc czytnik ekranu i automatyzacja czytają numer kontraktu zamiast osoby.
 * Cel linku widać w pasku stanu przeglądarki, a na kafelku dodatkowo w stojącej
 * obok etykiecie „Kontrakt #NNN".
 */
export function ContractPersonLink({ contractId, name, className }: Props) {
  return (
    <Link
      href={contractDetailHref(contractId)}
      className={cn(
        "rounded-sm hover:text-primary hover:underline underline-offset-2",
        "outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
    >
      {name}
    </Link>
  );
}
