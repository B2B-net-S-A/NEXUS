"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ArrowRight, Clock3, PhoneCall } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  candidateContactApi,
  candidateContactQueryKeys,
} from "@/lib/candidate-contact";
import { useCandidateContactFeature } from "@/hooks/useCandidateContactFeature";

export interface MyContactQueueWidgetProps {
  featureEnabledOverride?: boolean;
}

export function MyContactQueueWidget({
  featureEnabledOverride,
}: MyContactQueueWidgetProps = {}) {
  const contactFeature = useCandidateContactFeature({
    enabledOverride: featureEnabledOverride,
  });
  const query = useQuery({
    queryKey: candidateContactQueryKeys.queue(),
    // A contact owner may retain many slot-free handoff cases. Fetch the
    // endpoint maximum so those rows do not hide the at-most-20 actionable
    // calls when calculating dashboard counters.
    queryFn: () => candidateContactApi.queue({ limit: 100 }),
    enabled: contactFeature.enabled,
    staleTime: 30_000,
  });

  if (!contactFeature.enabled) return null;

  if (query.isError) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Moja kolejka kontaktu</CardTitle>
          <CardDescription>
            Kolejka jest chwilowo niedostępna lub funkcja nie została jeszcze
            aktywowana.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const data = query.data;
  const callbacks =
    data?.items.filter((item) => item.status === "callback_due").length ?? 0;
  const overdue =
    data?.items.filter((item) => {
      const due = item.callback_at ?? item.due_at;
      return (
        (item.status === "queued" || item.status === "callback_due") &&
        Boolean(due && new Date(due).getTime() < Date.now())
      );
    }).length ?? 0;

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle className="flex items-center gap-2">
            <PhoneCall aria-hidden className="h-4 w-4 text-primary" />
            Moja kolejka kontaktu
          </CardTitle>
          <CardDescription>
            Kandydat pojawia się tylko raz, razem ze wszystkimi ofertami.
          </CardDescription>
        </div>
        <span className="text-2xl font-semibold tabular-nums text-foreground">
          {data
            ? `${data.utilization.used}/${data.utilization.capacity}`
            : "—/20"}
        </span>
      </CardHeader>
      <CardContent>
        <div className="mb-4 grid grid-cols-2 gap-3">
          <div className="rounded-lg bg-muted/60 p-3">
            <p className="text-xl font-semibold tabular-nums text-foreground">
              {overdue}
            </p>
            <p className="text-xs text-muted-foreground">Zaległe</p>
          </div>
          <div className="rounded-lg bg-muted/60 p-3">
            <p className="flex items-center gap-1 text-xl font-semibold tabular-nums text-foreground">
              <Clock3 aria-hidden className="h-4 w-4 text-warning" />
              {callbacks}
            </p>
            <p className="text-xs text-muted-foreground">Callbacki</p>
          </div>
        </div>
        <Link
          href="/candidates/contact-queue"
          className={buttonVariants({ size: "sm" })}
        >
          Otwórz kolejkę
          <ArrowRight aria-hidden className="h-4 w-4" />
        </Link>
      </CardContent>
    </Card>
  );
}
