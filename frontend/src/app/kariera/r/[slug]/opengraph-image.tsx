import { headers } from "next/headers";
import { ImageResponse } from "next/og";

import { OG_SIZE, OgCard, ogFontsOrDefault, ogJobTiles } from "@/components/career/og";
import { fetchCareerBoard, fetchCareerJob } from "@/lib/career/server";
import { bigWord, boardCardFor } from "@/lib/career/site";
import { requestDisplayHost } from "@/lib/career/host";

export const size = OG_SIZE;
export const contentType = "image/png";
export const alt = "Rekrutacja IT — B2Bnetwork";
export const dynamic = "force-dynamic";

/**
 * Grafika posta na LinkedInie dla linku rekrutacji (od 24.11.2026 jak nagłówek
 * oferty): wielkie słowo z tablicy, tytuł, Lokalizacja · Tryb pracy · Umowa.
 */
export default async function Image({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  // Host z żądania, nie stała domena — grafika pokazuje adres, pod którym link działa.
  const host = requestDisplayHost(await headers());
  const [result, board] = await Promise.all([fetchCareerJob(slug.toLowerCase(), false), fetchCareerBoard()]);
  const job = result.ok ? result.data.job : null;
  const closed = result.ok && result.data.status === "closed";
  // Parametry ukryte przełącznikiem „pokaż” nie trafiają też do grafiki.
  const facts = job && job.show?.params !== false ? ogJobTiles(job.params) : [];
  // To samo wielkie słowo co na stronie oferty (krótka umiejętność z tablicy).
  const card =
    result.ok && board.ok ? boardCardFor(board.data.jobs, [result.data.canonical_slug, slug.toLowerCase()]) : null;
  return new ImageResponse(
    (
      <OgCard
        word={closed ? null : bigWord(card)}
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
        foot={closed ? "Zobacz inne rekrutacje →" : "Wyślij CV →"}
        host={host}
      />
    ),
    { ...OG_SIZE, fonts: await ogFontsOrDefault() },
  );
}
