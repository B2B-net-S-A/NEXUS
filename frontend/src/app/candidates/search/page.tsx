import { redirect } from "next/navigation";
import { candidatesModeHref } from "@/lib/candidates-mode";

/**
 * Wyszukiwarka jest trybem ekranu „Kandydaci" (21.09.2026). Stary adres
 * przekierowuje z zachowaniem stanu (`?s=` z filtrami, `?job=`), żeby
 * zapisane linki i „Wstecz" z profilu otwierały to samo wyszukiwanie.
 */
export default async function CandidatesSearchRedirect({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const incoming = await searchParams;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(incoming)) {
    if (Array.isArray(value)) value.forEach((v) => params.append(key, v));
    else if (value !== undefined) params.set(key, value);
  }
  redirect(candidatesModeHref("search", params));
}
