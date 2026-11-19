"use client";

import { useQuery } from "@tanstack/react-query";

import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type { ClientTab } from "@/lib/client-tab";
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
const ENDING_DAYS = 90;

/**
 * Umowa ramowa w nagłówku: do kiedy obowiązuje ta, na której klient stoi
 * (bezterminowa wygrywa, potem najpóźniejszy koniec). Klik prowadzi do umów.
 * Klucz zapytania jak w zakładce i Przeglądzie — jedno żądanie.
 */
export function ClientFrameworkChip({
  clientId,
  onOpen,
}: {
  clientId: number;
  onOpen: (tab: ClientTab) => void;
}) {
  const query = useQuery({
    queryKey: ["framework-contracts", clientId],
    queryFn: async () => (await dlPortalApi.listFrameworkContracts(clientId)).data,
  });
  const live = (query.data?.items ?? []).filter((item) => LIVE_STATUSES.has(item.status));
  if (live.length === 0) return null;
  const current = [...live].sort((a, b) =>
    (b.expiry_date ?? "9999-12-31").localeCompare(a.expiry_date ?? "9999-12-31"),
  )[0];
  const days = current.days_to_expiry;
  const tone: StatusDotTone =
    !current.expiry_date || days === null || days > ENDING_DAYS ? "neutral" : days < 0 ? "danger" : "warning";
  return (
    <button
      type="button"
      onClick={() => onOpen("umowy-ramowe")}
      className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      title={`${current.name} — otwórz „Umowy i aneksy”`}
      data-client-header-framework
    >
      {tone === "neutral" ? (
        <>
          Umowa ramowa{" "}
          <span className="font-medium text-foreground">
            {current.expiry_date ? `do ${formatIsoDatePl(current.expiry_date)}` : "bezterminowa"}
          </span>
        </>
      ) : (
        <StatusDot tone={tone}>
          {days !== null && days < 0
            ? `Umowa ramowa wygasła ${formatIsoDatePl(current.expiry_date)}`
            : `Umowa ramowa do ${formatIsoDatePl(current.expiry_date)}`}
        </StatusDot>
      )}
    </button>
  );
}
