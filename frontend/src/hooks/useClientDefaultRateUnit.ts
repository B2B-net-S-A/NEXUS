import { useQuery } from "@tanstack/react-query";

import { dlPortalApi, type OrderRateUnit } from "@/lib/api/dlPortal";

/**
 * Domyślna jednostka stawki dla formularzy zamówień klienta.
 *
 * Serwer wylicza najczęstszą NIE-miesięczną jednostkę z istniejących zamówień
 * klienta (nigdy `monthly` — patrz backend `default_rate_unit_for_client`).
 * Formularze („Nowy kontraktor", „Uzupełnij/Przedłuż zamówienie") używają jej
 * jako wartości POCZĄTKOWEJ pola „jednostka stawki" zamiast twardego `monthly`;
 * użytkownik może ją zmienić ręcznie.
 *
 * Cache'owana per klient i długo świeża — zakładka i osadzone w niej dialogi
 * wołają ten sam klucz, więc dialog dostaje wartość z cache już przy pierwszym
 * renderze (bez migotania `monthly`).
 */
export function useClientDefaultRateUnit(clientId: number | null | undefined) {
  return useQuery({
    queryKey: ["client-default-rate-unit", clientId],
    queryFn: async (): Promise<OrderRateUnit> => {
      const res = await dlPortalApi.getDefaultRateUnit(clientId as number);
      return res.data.rate_unit;
    },
    enabled: typeof clientId === "number" && clientId > 0,
    // Jednostka rozliczeniowa klienta zmienia się rzadko — nie odświeżaj przy
    // każdym powrocie focusu do zakładki.
    staleTime: 5 * 60_000,
  });
}
