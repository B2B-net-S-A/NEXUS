import { redirect } from "next/navigation";
import { candidatesModeHref } from "@/lib/candidates-mode";
import { searchStateToListHref } from "@/lib/candidates-search-redirect";

/**
 * Stary adres wyszukiwarki. Od 22.09.2026 wyszukiwanie żyje na liście
 * „Kandydaci": stan (`?s=` z filtrami) przechodzi wprost na listę. Adres
 * z rekrutacją (`?job=`) dalej otwiera wyszukiwarkę rekrutacji.
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
  if (params.get("job")) redirect(candidatesModeHref("search", params));
  redirect(searchStateToListHref(params));
}
