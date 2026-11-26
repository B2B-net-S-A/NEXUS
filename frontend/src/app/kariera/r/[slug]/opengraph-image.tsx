import { headers } from "next/headers";
import { ImageResponse } from "next/og";

import { OG_SIZE, ogFontsOrDefault } from "@/components/career/og";
import { OgOfferCard, type OgOfferMap } from "@/components/career/ogMapCard";
import { requestDisplayHost } from "@/lib/career/host";
import { closedSvg, offerFocusSvg, remoteSvg } from "@/lib/career/mapSvg";
import { offerOgLine, offerOgSub } from "@/lib/career/ogText";
import { officeNote, offerMapMode } from "@/lib/career/polandMap";
import { fetchCareerBoard, fetchCareerJob } from "@/lib/career/server";
import { bigWord, boardCardFor, facetCounts, jobCities, offerTags } from "@/lib/career/site";

export const size = OG_SIZE;
export const contentType = "image/png";
export const alt = "Rekrutacja IT — B2B Network";
export const dynamic = "force-dynamic";

/**
 * Grafika podglądu linku do oferty (język A, makiety OG-oferta i OG-zdalna,
 * 26.11.2026): technologie z tablicy, stanowisko, „{miasto} · {tryb} · B2B”
 * i mapa z podświetlonym miastem; praca zdalna = cała mapa świeci; zamknięta
 * = plakietka i przerywany obrys. Bez udawanego przycisku.
 */
export default async function Image({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  // Host z żądania, nie stała domena — grafika pokazuje adres, pod którym link działa.
  const host = requestDisplayHost(await headers());
  const [result, board] = await Promise.all([fetchCareerJob(slug.toLowerCase(), false), fetchCareerBoard()]);
  const data = result.ok ? result.data : null;
  const job = data?.job ?? null;
  const closed = data?.status === "closed";
  // Parametry ukryte przełącznikiem „pokaż” nie trafiają też do grafiki.
  const p = job && job.show?.params !== false ? job.params : null;
  const jobs = board.ok ? board.data.jobs : [];
  const card = data ? boardCardFor(jobs, [data.canonical_slug, slug.toLowerCase()]) : null;
  const mode = offerMapMode(closed ? "closed" : "open", p, (city) => jobCities({ city }));
  let map: OgOfferMap = { kind: "none" };
  if (mode.kind === "closed") map = { kind: "closed", map: closedSvg() };
  else if (mode.kind === "remote") map = { kind: "remote", map: remoteSvg() };
  else if (mode.kind === "focus") {
    const focus = offerFocusSvg(facetCounts(jobs), mode.cities);
    map = { kind: "focus", map: focus, lit: focus.lit, cities: mode.cities.join(", "), note: officeNote(p) };
  }
  return new ImageResponse(
    (
      <OgOfferCard
        tags={closed ? [] : offerTags(bigWord(card), card?.must ?? [])}
        status={closed ? "Rekrutacja zamknięta" : null}
        title={job?.title.trim() || "Rekrutacja IT"}
        line={closed ? null : offerOgLine(p)}
        sub={closed ? null : offerOgSub(p, data?.recruiter.first_name ?? "")}
        map={map}
        host={host}
      />
    ),
    { ...OG_SIZE, fonts: await ogFontsOrDefault() },
  );
}
