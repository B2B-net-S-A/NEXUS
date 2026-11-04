import { headers } from "next/headers";
import { ImageResponse } from "next/og";

import { OG_SIZE, OgCard, ogFontsOrDefault } from "@/components/career/og";
import { requestDisplayHost } from "@/lib/career/host";

export const size = OG_SIZE;
export const contentType = "image/png";
export const alt = "Rekrutacje IT — B2B Network";
export const dynamic = "force-dynamic";

/**
 * Grafika strony głównej kariery na LinkedInie (etap 6, 20.10.2026) — wcześniej
 * link do `kariera.b2bnetwork.pl` wklejał się bez obrazka. Od 29.10.2026
 * w barwach marki (`OgCard`).
 */
export default async function Image() {
  const host = requestDisplayHost(await headers());
  return new ImageResponse(
    (
      <OgCard
        kicker="Kariera w B2B Network"
        title="Otwarte rekrutacje IT"
        facts={[
          { label: "Współpraca", value: "Kontrakty B2B" },
          { label: "Tryb pracy", value: "Zdalnie i hybrydowo" },
          { label: "Zgłoszenie", value: "2 minuty" },
        ]}
        foot="Zobacz rekrutacje →"
        host={host}
      />
    ),
    { ...OG_SIZE, fonts: await ogFontsOrDefault() },
  );
}
