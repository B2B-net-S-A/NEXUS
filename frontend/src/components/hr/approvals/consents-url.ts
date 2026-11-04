// Adres „Moich zgód” — od 22.10.2026 zakładka „Zgody i wydatki” w „Moim czasie”.
//
// Lustro `my_request_link` w `backend/app/services/hr/approvals/service.py`
// (dzwonek i mail do autora zgody). Stary `/people/consents` przekierowuje tu
// z `request` i `new`.

export const MY_CONSENTS_TAB = "consents";

/** `/my-time?tab=consents[&request=<id>][&new=1]`. */
export function myConsentsHref({
  request,
  isNew,
}: { request?: number | null; isNew?: boolean } = {}): string {
  const params = new URLSearchParams({ tab: MY_CONSENTS_TAB });
  if (request) params.set("request", String(request));
  if (isNew) params.set("new", "1");
  return `/my-time?${params.toString()}`;
}

/** Przekierowanie ze starego `/people/consents?…` — tylko `request` (liczba) i `new=1`. */
export function consentsRedirectHref(search: string): string {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const request = Number(params.get("request"));
  return myConsentsHref({
    request: Number.isInteger(request) && request > 0 ? request : null,
    isNew: params.get("new") === "1",
  });
}
