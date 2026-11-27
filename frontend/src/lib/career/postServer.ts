import { JOB_SLUG_RE, primaryCareerHost } from "./host";
import { buildPostData, type PostData } from "./postGraphic";
import { fetchCareerBoard, fetchCareerJob } from "./server";

/**
 * Dane grafiki posta po stronie serwera (trasy `grafika-posta` i `…/dane`).
 * `null` = nieznany link, zamknięta rekrutacja albo awaria API. Odczyt nie
 * liczy się jako wejście kandydata (jak grafika OG).
 */
export async function loadPostData(rawSlug: string): Promise<PostData | null> {
  const slug = rawSlug.toLowerCase();
  if (!JOB_SLUG_RE.test(slug)) return null;
  const [result, board] = await Promise.all([fetchCareerJob(slug, false), fetchCareerBoard()]);
  if (!result.ok) return null;
  // Stopka: domena kariery, nie host żądania — grafikę pobiera się z NEXUSA,
  // a link w komentarzu prowadzi na stronę kariery.
  return buildPostData(result.data, board.ok ? board.data.jobs : [], primaryCareerHost(), slug);
}
