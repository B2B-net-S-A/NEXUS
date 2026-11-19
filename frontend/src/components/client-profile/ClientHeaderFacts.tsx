"use client";

import { useQuery } from "@tanstack/react-query";

import { StatusDot } from "@/components/ds/StatusDot";
import { dlPortalApi, type FrameworkContractRead } from "@/lib/api/dlPortal";
import { formatIsoDatePl } from "@/lib/date-pl";
import type { ClientProfileResponse } from "@/types/client-profile";

import { useClientProfile } from "./useClientProfile";

/**
 * Stan współpracy w nagłówku klienta (makieta 19.11.2026) — ta sama reguła co
 * lista „Klienci”: ktoś od nas pracuje albo zaczyna u klienta, albo trwa
 * rekrutacja. Zastąpił w nagłówku „Status klienta”, który był drugim,
 * niezależnym podziałem i prawie zawsze mówił „Aktywny”.
 */
export function isWorkingWithClient(profile: ClientProfileResponse): boolean {
  return (
    profile.summary.active_consultants > 0 ||
    (profile.planned_consultants?.length ?? 0) > 0 ||
    profile.summary.open_jobs > 0
  );
}

export function ClientStateChip({ clientId }: { clientId: number }) {
  const { data } = useClientProfile(clientId);
  if (!data?.summary) return null;
  const working = isWorkingWithClient(data);
  return (
    <StatusDot
      tone={working ? "success" : "neutral"}
      title={
        working
          ? "Pracuje u nich ktoś od nas, ktoś zaczyna albo trwa rekrutacja."
          : "Dziś nikt od nas u nich nie pracuje i nie ma otwartej rekrutacji."
      }
    >
      {working ? "Współpracujemy" : "Bez bieżącej pracy"}
    </StatusDot>
  );
}

const LIVE_STATUSES = new Set(["active", "pending_signature"]);

/**
 * Umowa ramowa, na której klient stoi: bezterminowa wygrywa, potem
 * najpóźniejszy koniec. Liczą się obowiązujące i czekające na podpis.
 */
export function currentFrameworkContract(
  items: readonly FrameworkContractRead[],
): FrameworkContractRead | null {
  const live = items.filter((item) => LIVE_STATUSES.has(item.status));
  if (live.length === 0) return null;
  return [...live].sort((a, b) =>
    (b.expiry_date ?? "9999-12-31").localeCompare(a.expiry_date ?? "9999-12-31"),
  )[0];
}

/**
 * Dopisek przy sekcji „Umowa i pieniądze”: „bezterminowa”, „do 31.12.2026”
 * albo „wygasła 03.01.2026”. Do 19.11.2026 (wieczór) był to chip w nagłówku;
 * nagłówek wrócił do jednego rzędu (decyzja Artura). Ostrzeżenie od 90 dni
 * przed końcem pokazuje „Wymaga uwagi” w Przeglądzie.
 */
export function frameworkSectionMeta(contract: FrameworkContractRead): { text: string; title: string } {
  const expired = contract.days_to_expiry !== null && contract.days_to_expiry < 0;
  const text = !contract.expiry_date
    ? "bezterminowa"
    : expired
      ? `wygasła ${formatIsoDatePl(contract.expiry_date)}`
      : `do ${formatIsoDatePl(contract.expiry_date)}`;
  return { text, title: `Umowa ramowa: ${contract.name}` };
}

/** Klucz zapytania jak w zakładce umów i w Przeglądzie — jedno żądanie. */
export function useClientFrameworkMeta(
  clientId: number,
  enabled: boolean,
): { text: string; title: string } | null {
  const query = useQuery({
    queryKey: ["framework-contracts", clientId],
    queryFn: async () => (await dlPortalApi.listFrameworkContracts(clientId)).data,
    enabled,
  });
  if (!enabled) return null;
  const current = currentFrameworkContract(query.data?.items ?? []);
  return current ? frameworkSectionMeta(current) : null;
}
