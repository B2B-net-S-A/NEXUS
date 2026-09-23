import { headers } from "next/headers";
import { ImageResponse } from "next/og";

import { OG_COLORS, OG_SIZE, OgFrame, ogFontsOrDefault } from "@/components/career/og";
import { fetchCareerRecruiter } from "@/lib/career/server";
import { recruiterLogin } from "@/lib/career/format";
import { requestDisplayHost } from "@/lib/career/host";

export const size = OG_SIZE;
export const contentType = "image/png";
export const alt = "Rekrutacje IT — Dynaminds";
export const dynamic = "force-dynamic";

/** Grafika posta dla stałego linku rekrutera (makieta OgGeneral). */
export default async function Image({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  // Host z żądania, nie stała domena — grafika pokazuje adres, pod którym link działa.
  const host = requestDisplayHost(await headers());
  const result = await fetchCareerRecruiter(slug.toLowerCase(), false);
  const firstName = result.ok ? result.data.recruiter.first_name : "";
  const recruiterSlug = result.ok ? result.data.recruiter.slug : slug;
  return new ImageResponse(
    (
      <OgFrame
        path={`~/dynaminds/kariera/${recruiterSlug}`}
        rightLabel="ARCHITECTS OF THE UNSEEN"
        command={
          <>
            <span style={{ color: OG_COLORS.red, marginRight: 16 }}>$</span>
            whoami
            <span style={{ color: OG_COLORS.gray, marginLeft: 16 }}>
              — {recruiterLogin(firstName)}
            </span>
          </>
        }
        titleFirst="Szukasz kolejnego"
        titleSecond="projektu IT?"
        footLeft="// zostaw CV — odezwę się z konkretem"
        footLeftItalic
        host={host}
      />
    ),
    { ...OG_SIZE, fonts: await ogFontsOrDefault() },
  );
}
