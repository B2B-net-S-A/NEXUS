import { headers } from "next/headers";
import { ImageResponse } from "next/og";

import { OG_SIZE, OgCard, ogFontsOrDefault, ogJobTiles } from "@/components/career/og";
import { fetchCareerJob } from "@/lib/career/server";
import { requestDisplayHost } from "@/lib/career/host";

export const size = OG_SIZE;
export const contentType = "image/png";
export const alt = "Rekrutacja IT — B2B Network";
export const dynamic = "force-dynamic";

/**
 * Grafika posta na LinkedInie dla linku rekrutacji: tytuł, Lokalizacja, Tryb
 * pracy i Umowa w kaflach, kolory szablonu rekrutacji (te same co strona).
 */
export default async function Image({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  // Host z żądania, nie stała domena — grafika pokazuje adres, pod którym link działa.
  const host = requestDisplayHost(await headers());
  const result = await fetchCareerJob(slug.toLowerCase(), false);
  const job = result.ok ? result.data.job : null;
  const closed = result.ok && result.data.status === "closed";
  // Parametry ukryte przełącznikiem „pokaż” nie trafiają też do grafiki.
  const facts = job && job.show?.params !== false ? ogJobTiles(job.params) : [];
  return new ImageResponse(
    (
      <OgCard
        theme={result.ok ? result.data.theme : null}
        status={
          result.ok
            ? closed
              ? { label: "Rekrutacja zamknięta", closed: true }
              : { label: "Rekrutacja otwarta" }
            : null
        }
        kicker="Rekrutacja IT"
        title={job?.title.trim() || "Rekrutacja IT"}
        facts={closed ? [] : facts}
        foot={closed ? "Zobacz inne rekrutacje →" : "Aplikuj w 2 minuty →"}
        host={host}
      />
    ),
    { ...OG_SIZE, fonts: await ogFontsOrDefault() },
  );
}
