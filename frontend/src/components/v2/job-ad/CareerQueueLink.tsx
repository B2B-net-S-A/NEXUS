"use client";

/**
 * Wejście do „Strona kariery do uzupełnienia” na liście rekrutacji
 * (21.10.2026): ile otwartych rekrutacji osoby nie wisi jeszcze na stronie
 * kariery. Same liczby (`limit: 0`). Rola bez prawa publikacji dostaje 403 —
 * wtedy przycisku nie ma; zero rekrutacji = też nie ma.
 */

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Megaphone } from "lucide-react";

import { Button } from "@/components/ui/button";
import { careerQueueQueryKey, jobAdApi } from "@/lib/api/jobAd";

export function CareerQueueLink({
  api = jobAdApi,
}: {
  api?: Pick<typeof jobAdApi, "careerQueue">;
}) {
  const counts = useQuery({
    queryKey: careerQueueQueryKey("mine", 0),
    queryFn: () => api.careerQueue("mine", 0),
    retry: false,
    staleTime: 60_000,
  });
  if (!counts.isSuccess) return null;
  // Head of Recruitment i admin zwykle nie mają „swoich” rekrutacji.
  const mine = counts.data.mine_count;
  const count = mine > 0 ? mine : counts.data.all_count;
  if (count === 0) return null;
  const label = mine > 0 ? "Twoje otwarte rekrutacje" : "Otwarte rekrutacje";
  return (
    <Button size="sm" variant="outline" asChild>
      <Link
        href="/jobs/strona-kariery"
        title={`${label} bez strony kariery: ${count}`}
        data-testid="career-queue-link"
      >
        <Megaphone className="h-4 w-4" aria-hidden="true" />
        Strona kariery · {count}
      </Link>
    </Button>
  );
}
