import { ImageResponse } from "next/og";

import { ogFontsOrDefault } from "@/components/career/og";
import { POST_SIZE, PostCardFacts, PostCardMap, PostCarouselSlide } from "@/components/career/ogPostCard";
import { carouselSlides, isPostVariant } from "@/lib/career/postGraphic";
import { loadPostData } from "@/lib/career/postServer";

export const dynamic = "force-dynamic";

/**
 * Grafika posta na LinkedInie (1080×1350 PNG): `?v=mapa|konkrety|karuzela`,
 * przy karuzeli `&s=<nr slajdu od 1>`. Publiczna jak grafika OG — te same dane
 * co strona oferty (opublikowana wersja, bez klienta i stawek). Zamknięta
 * rekrutacja, nieznany link albo slajd spoza karuzeli = 404.
 */
export async function GET(request: Request, { params }: { params: Promise<{ slug: string }> }) {
  const url = new URL(request.url);
  const variant = url.searchParams.get("v") ?? "mapa";
  if (!isPostVariant(variant)) return new Response(null, { status: 404 });
  const data = await loadPostData((await params).slug);
  if (!data) return new Response(null, { status: 404 });

  let body: React.ReactElement;
  if (variant === "karuzela") {
    const slides = carouselSlides(data);
    const index = Number(url.searchParams.get("s") ?? "1") - 1;
    if (!Number.isInteger(index) || index < 0 || index >= slides.length) return new Response(null, { status: 404 });
    body = <PostCarouselSlide d={data} slides={slides} index={index} />;
  } else {
    body = variant === "konkrety" ? <PostCardFacts d={data} /> : <PostCardMap d={data} />;
  }
  return new ImageResponse(body, {
    ...POST_SIZE,
    fonts: await ogFontsOrDefault(),
    // Zmiana opisu po zatwierdzeniu ma być widać od razu — bez długiego cache.
    headers: { "Cache-Control": "public, max-age=60" },
  });
}
