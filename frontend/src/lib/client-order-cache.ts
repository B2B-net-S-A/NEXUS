import type { QueryClient, QueryKey } from "@tanstack/react-query";

/**
 * Klucze zapytań, które czytają zamówienia klienta. Zapis zamówienia (edycja,
 * zakończenie, przedłużenie) zmienia każde z nich: karty kontraktorów, karty
 * zamówień MD/kosztowych, historię zamówień, dokumenty, alerty Delivery Leada
 * i kafle profilu klienta (stawki z zamówienia, „Aktywne MRR”).
 *
 * Runda 10 (R10-N15-6): karty kontraktorów odświeżały tylko trzy z nich,
 * więc zakładka Profil pokazywała stare stawki do 30 s po zapisie.
 */
export function clientOrderQueryKeys(clientId: number): QueryKey[] {
  return [
    ["dl-orders-grouped", clientId],
    ["client-order-groups", clientId],
    ["order-group-events", clientId],
    ["order-documents"],
    ["contract-documents"],
    ["dl-alerts"],
    ["client-profile", clientId],
  ];
}

export function invalidateClientOrderQueries(
  queryClient: QueryClient,
  clientId: number,
): Promise<void> {
  return Promise.all(
    clientOrderQueryKeys(clientId).map((queryKey) =>
      queryClient.invalidateQueries({ queryKey }),
    ),
  ).then(() => undefined);
}
