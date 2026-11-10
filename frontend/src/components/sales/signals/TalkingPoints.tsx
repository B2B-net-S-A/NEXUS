"use client";

import { ExternalLink } from "lucide-react";

import { safeHref } from "@/components/sales/format";
import { Badge } from "@/components/ui/badge";
import { useCompanyBriefing } from "@/lib/api/sales";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

const MODE_LABELS = {
  first_call: "na pierwszą rozmowę",
  ongoing: "do prowadzonej szansy",
} as const;

interface TalkingPointsProps {
  companyId: number | null | undefined;
  /** Bez punktów pokaż zdanie, że bot ich jeszcze nie przygotował (panel sygnału). */
  showEmpty?: boolean;
  className?: string;
}

/**
 * Punkty do rozmowy z bota researchu: 3–4 aktualności o firmie, do których handlowiec
 * może nawiązać. Z wyłączonym kanałem, w trakcie wczytywania i przy błędzie nic nie
 * pokazuje: to dodatek do karty, nie jej warunek.
 */
export function TalkingPoints({ companyId, showEmpty = false, className }: TalkingPointsProps) {
  const query = useCompanyBriefing(companyId);
  if (!query.isSuccess || !query.data.enabled) return null;
  const briefing = query.data.briefing;
  if (!briefing || briefing.points.length === 0) {
    return showEmpty ? (
      <p className={cn("text-xs text-muted-foreground", className)}>
        Bot jeszcze nie przygotował punktów do rozmowy o tej firmie.
      </p>
    ) : null;
  }
  return (
    <section className={cn("space-y-1", className)} aria-label="Punkty do rozmowy">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-xs font-medium text-foreground">
          Punkty do rozmowy {MODE_LABELS[briefing.mode]}
        </h3>
        <Badge variant="neutral" size="sm">
          Research bota, sprawdź źródło
        </Badge>
        <span className="text-xs text-muted-foreground">{formatIsoDatePl(briefing.generated_at)}</span>
      </div>
      <ul className="list-disc space-y-0.5 pl-4">
        {briefing.points.map((point, index) => {
          const href = safeHref(point.url);
          return (
            <li key={index} className="text-xs leading-snug text-muted-foreground">
              {point.text}
              {point.published && <span className="tabular-nums"> · {formatIsoDatePl(point.published)}</span>}
              {href && (
                <a
                  href={href}
                  target="_blank"
                  rel="noreferrer"
                  className="ml-1 inline-flex items-center gap-0.5 text-primary hover:underline"
                >
                  źródło <ExternalLink className="h-3 w-3" aria-hidden />
                </a>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
