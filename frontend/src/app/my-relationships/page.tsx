import { redirect } from "next/navigation";
import { legacyRedirectTarget } from "@/lib/clients-workspace";

/**
 * „Moje relacje" (od 22.09.2026 tryb „Kluczowe relacje" ekranu Klienci) od
 * 18.11.2026 nie mają osobnego widoku: relacje są pod klientem (Przegląd,
 * Ludzie › Kontakty i relacje), a bez kontaktu — w „Wymaga uwagi” na liście.
 * Stary adres przekierowuje na listę (zapisane linki, powiadomienia w bazie).
 */
export default async function MyRelationshipsRedirect({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  redirect(legacyRedirectTarget("/clients", {}, await searchParams));
}
