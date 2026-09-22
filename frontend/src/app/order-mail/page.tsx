import { redirect } from "next/navigation";
import { legacyRedirectTarget } from "@/lib/clients-workspace";

/**
 * „Zamówienia z maila" to od 22.09.2026 tryb „Skrzynka zamówień" w Kontraktach.
 * Stary adres przekierowuje na stałe (zapisane linki, powiadomienia w bazie).
 */
export default async function OrderMailRedirect({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  redirect(legacyRedirectTarget("/contracts", { view: "order-mail" }, await searchParams));
}
