"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Keeps stale client detail links canonical after the API follows a merge
 * redirect. Browsers follow the backend's HTTP 308 before Axios exposes the
 * response, but the final client payload still carries the canonical id.
 */
export function useCanonicalClientRedirect(
  requestedId: string | string[] | undefined,
  canonicalClientId: number | null | undefined,
) {
  const router = useRouter();

  useEffect(() => {
    const routeId = Array.isArray(requestedId) ? requestedId[0] : requestedId;
    const parsedRouteId = routeId ? Number(routeId) : Number.NaN;

    if (
      !Number.isSafeInteger(parsedRouteId) ||
      !Number.isSafeInteger(canonicalClientId) ||
      canonicalClientId == null ||
      canonicalClientId <= 0 ||
      parsedRouteId === canonicalClientId
    ) {
      return;
    }

    router.replace(`/clients/${canonicalClientId}`);
  }, [canonicalClientId, requestedId, router]);
}
