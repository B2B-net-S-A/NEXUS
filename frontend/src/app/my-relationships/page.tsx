import { redirect } from "next/navigation";
import { legacyRedirectTarget } from "@/lib/clients-workspace";

/**
 * „Moje relacje" to od 22.09.2026 tryb „Kluczowe relacje" ekranu Klienci.
 * Stary adres przekierowuje na stałe (zapisane linki, powiadomienia w bazie).
 */
export default async function MyRelationshipsRedirect({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  redirect(legacyRedirectTarget("/clients", { view: "contacts" }, await searchParams));
}
