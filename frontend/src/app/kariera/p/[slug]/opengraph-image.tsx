import { headers } from "next/headers";
import { ImageResponse } from "next/og";

import { OG_SIZE, OgCard, ogFontsOrDefault } from "@/components/career/og";
import { fetchCareerRecruiter } from "@/lib/career/server";
import { requestDisplayHost } from "@/lib/career/host";

export const size = OG_SIZE;
export const contentType = "image/png";
export const alt = "Rekrutacje IT — B2B Network";
export const dynamic = "force-dynamic";

/** Grafika posta dla stałego linku rekrutera: inicjał i imię, pytanie, „Zostaw CV”. */
export default async function Image({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  // Host z żądania, nie stała domena — grafika pokazuje adres, pod którym link działa.
  const host = requestDisplayHost(await headers());
  const result = await fetchCareerRecruiter(slug.toLowerCase(), false);
  const firstName = result.ok ? result.data.recruiter.first_name.trim() : "";
  return new ImageResponse(
    (
      <OgCard
        person={
          firstName
            ? {
                initial: firstName.charAt(0).toLocaleUpperCase("pl-PL"),
                name: `${firstName} · rekrutacje IT w B2B Network`,
              }
            : null
        }
        kicker={firstName ? null : "Kariera w B2B Network"}
        title="Szukasz kolejnego projektu IT?"
        foot="Zostaw CV — odezwę się →"
        host={host}
      />
    ),
    { ...OG_SIZE, fonts: await ogFontsOrDefault() },
  );
}
