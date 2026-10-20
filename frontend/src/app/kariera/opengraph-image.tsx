import { headers } from "next/headers";
import { ImageResponse } from "next/og";

import { OG_SIZE, OgFrame, ogFontsOrDefault } from "@/components/career/og";
import { OG_COLORS } from "@/components/career/palette";
import { requestDisplayHost } from "@/lib/career/host";

export const size = OG_SIZE;
export const contentType = "image/png";
export const alt = "Rekrutacje IT — B2B Network";
export const dynamic = "force-dynamic";

/**
 * Grafika strony głównej kariery na LinkedInie (etap 6, 20.10.2026) — wcześniej
 * link do `kariera.b2bnetwork.pl` wklejał się bez obrazka.
 */
export default async function Image() {
  const host = requestDisplayHost(await headers());
  return new ImageResponse(
    (
      <OgFrame
        path="~/b2bnetwork/kariera"
        rightLabel="REKRUTACJE IT"
        command={
          <>
            <span style={{ color: OG_COLORS.red, marginRight: 16 }}>$</span>
            ls ~/rekrutacje --open
          </>
        }
        titleFirst="Otwarte rekrutacje IT"
        titleSecond="B2B Network."
        footLeft="[projekty b2b · zdalnie, hybrydowo, stacjonarnie]"
        host={host}
      />
    ),
    { ...OG_SIZE, fonts: await ogFontsOrDefault() },
  );
}
