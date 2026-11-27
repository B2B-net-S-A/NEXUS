import { NextResponse } from "next/server";

import { carouselSlides, postText } from "@/lib/career/postGraphic";
import { loadPostData } from "@/lib/career/postServer";

export const dynamic = "force-dynamic";

/**
 * Dane zakładki „Post na LinkedIn” w NEXUSIE: kadr grafiki (podgląd rysuje się
 * w przeglądarce tym samym komponentem), treść posta i lista slajdów karuzeli.
 * Ta sama domena co aplikacja, więc bez CORS; te same dane co strona oferty.
 */
export async function GET(_request: Request, { params }: { params: Promise<{ slug: string }> }) {
  const data = await loadPostData((await params).slug);
  if (!data) return NextResponse.json({ detail: "Brak opublikowanej, otwartej rekrutacji pod tym linkiem." }, { status: 404 });
  return NextResponse.json(
    { post: data, text: postText(data), slides: carouselSlides(data) },
    { headers: { "Cache-Control": "no-store" } },
  );
}
