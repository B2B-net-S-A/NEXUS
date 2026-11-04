import { redirect } from "next/navigation";
import { legacyCvGeneratorHref } from "@/lib/cv-generator";

/**
 * Osobny ekran „Generator CV” zniknął 13.10.2026 (decyzja Artura): CV powstaje
 * wyłącznie w rekrutacji — karta „CV do klienta” w panelu osoby, profil
 * kandydata, okno QC. Stary adres przekierowuje (zakładki, stare powiadomienia).
 */
export default async function CvGeneratorRedirect({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  redirect(legacyCvGeneratorHref(await searchParams));
}
