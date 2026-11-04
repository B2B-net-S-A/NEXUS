"use client";

import { useEffect, useRef, useState } from "react";

import "@/components/career/layouts/brandFonts.css";
import { OgCard, type OgFact } from "@/components/career/ogCard";

/**
 * Podgląd posta na LinkedInie — miniatura grafiki Open Graph strony kariery.
 *
 * WYJĄTEK OD ZASADY TOKEN-FIRST: górna część karty to ZEWNĘTRZNY obraz —
 * ten sam kadr `OgCard`, który rysuje `next/og` (od 29.10.2026, barwy marki
 * B2B Network), przeskalowany do szerokości karty. Ma wyglądać tak samo
 * w każdym motywie NEXUSA, bo tak zobaczy go LinkedIn. Podpis pod obrazem
 * (tytuł + domena) to już NEXUS: tokeny.
 */

const OG_WIDTH = 1200;
const OG_HEIGHT = 630;

export interface LinkedInPreviewCardProps {
  /** Mały napis nad tytułem grafiki (np. „Rekrutacja IT”). */
  kicker?: string | null;
  /** Tytuł grafiki; ostatnie słowo z liter dostaje czerwień marki. */
  headline: string;
  /** Kafle grafiki rekrutacji (Lokalizacja, Tryb pracy, Umowa). */
  facts?: OgFact[];
  /** Stały link rekrutera: inicjał i podpis nad tytułem. */
  person?: { initial: string; name: string } | null;
  /** Wezwanie w prawym dolnym rogu grafiki. */
  foot: string;
  /** Plakietka statusu (rekrutacja otwarta). */
  status?: { label: string; closed?: boolean } | null;
  /** Tytuł karty pod obrazem. */
  cardTitle: string;
  /** Domena pod tytułem. */
  host: string;
  /** Szablon graficzny rekrutacji — kolory jak w grafice OG. */
  theme?: string | null;
}

export function LinkedInPreviewCard({
  kicker,
  headline,
  facts,
  person,
  foot,
  status,
  cardTitle,
  host,
  theme,
}: LinkedInPreviewCardProps) {
  const frame = useRef<HTMLDivElement>(null);
  // Skala kadru 1200×630 do szerokości karty; bez ResizeObserver (jsdom) — typowa szerokość okna.
  const [scale, setScale] = useState(0.3);
  useEffect(() => {
    const node = frame.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const width = entry.contentRect.width;
      if (width > 0) setScale(width / OG_WIDTH);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <figure
      className="overflow-hidden rounded-lg border border-border bg-card"
      aria-label="Podgląd posta na LinkedInie"
      data-testid="linkedin-preview"
    >
      <div
        ref={frame}
        className="relative w-full overflow-hidden"
        style={{ aspectRatio: `${OG_WIDTH} / ${OG_HEIGHT}` }}
        aria-hidden="true"
      >
        <div
          className="absolute left-0 top-0 origin-top-left"
          style={{ width: OG_WIDTH, height: OG_HEIGHT, transform: `scale(${scale})` }}
        >
          <OgCard
            theme={theme}
            status={status}
            kicker={kicker}
            title={headline}
            facts={facts}
            person={person}
            foot={foot}
            host={host}
          />
        </div>
      </div>
      <figcaption className="px-3 py-2.5">
        <div className="truncate text-sm font-semibold text-foreground">{cardTitle}</div>
        <div className="truncate text-xs text-muted-foreground">{host}</div>
      </figcaption>
    </figure>
  );
}
