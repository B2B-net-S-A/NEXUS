"use client";

import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";

export const cloudTalkStatusQueryKey = ["cloudtalk-status"] as const;

interface CloudTalkStatus {
  enabled: boolean;
}

/**
 * Whether click-to-call through CloudTalk is switched on for this deployment
 * (`GET /api/calls/cloudtalk-status`).
 *
 * Fails closed: while the status is loading, when the request fails (403,
 * network, older backend) or when the payload is malformed, the answer is
 * `false`. A call button that always ends in "CloudTalk wyłączony" is worse
 * than no button — the phone number is still shown as text.
 */
export function useCloudTalkEnabled(options: { enabled?: boolean } = {}): boolean {
  const query = useQuery<CloudTalkStatus>({
    queryKey: cloudTalkStatusQueryKey,
    queryFn: ({ signal }) =>
      api
        .get<CloudTalkStatus>("/api/calls/cloudtalk-status", { signal })
        .then((response) => response.data),
    enabled: options.enabled ?? true,
    staleTime: 5 * 60_000,
    retry: false,
  });
  return query.data?.enabled === true;
}
