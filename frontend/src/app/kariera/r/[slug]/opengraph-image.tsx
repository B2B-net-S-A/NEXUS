import { ImageResponse } from "next/og";

import { OG_COLORS, OG_SIZE, OgFrame, ogFontsOrDefault } from "@/components/career/og";
import { fetchCareerJob } from "@/lib/career/api";
import { jobHandle, paramsSummary, splitTitle } from "@/lib/career/format";
import { primaryCareerHost } from "@/lib/career/host";

export const size = OG_SIZE;
export const contentType = "image/png";
export const alt = "Rekrutacja IT — Dynaminds";
export const dynamic = "force-dynamic";

/** Grafika posta na LinkedInie dla linku rekrutacji (makieta OgImage). */
export default async function Image({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const result = await fetchCareerJob(slug.toLowerCase());
  const job = result.ok ? result.data.job : { slug, title: "Rekrutacja IT" };
  const closed = result.ok && result.data.status === "closed";
  const title = splitTitle(job.title);
  const summary = result.ok ? paramsSummary(result.data.job.params) : "";
  return new ImageResponse(
    (
      <OgFrame
        path="~/dynaminds/kariera"
        rightLabel={closed ? "REKRUTACJA ZAMKNIĘTA" : "REKRUTACJA OTWARTA"}
        command={
          <>
            <span style={{ color: OG_COLORS.red, marginRight: 16 }}>$</span>
            cat /rekrutacje/{jobHandle(job)}
          </>
        }
        titleFirst={title.first}
        titleSecond={title.second}
        footLeft={summary ? `[${summary}]` : "[rekrutacja it]"}
        host={primaryCareerHost()}
      />
    ),
    { ...OG_SIZE, fonts: await ogFontsOrDefault() },
  );
}
