import { redirect } from "next/navigation";
import { legacyRedirectTarget } from "@/lib/clients-workspace";

/**
 * „Panel klientów" to od 22.09.2026 przełącznik „Moi klienci" na liście Klienci.
 * Stary adres przekierowuje na stałe (zapisane linki, powiadomienia w bazie).
 */
export default async function MyClientsRedirect({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  redirect(legacyRedirectTarget("/clients", { mine: "1" }, await searchParams));
}
