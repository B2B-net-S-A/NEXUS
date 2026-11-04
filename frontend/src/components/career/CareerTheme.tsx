import "./career.css";

import { careerDisplayFont, careerMonoFont } from "./fonts";

/**
 * Korzeń motywu terminala: fonty, tło z siatką, zmienne kolorów.
 *
 * `page` — prawdziwa strona `/kariera` (nie harness): `career.css` barwi wtedy
 * na czarno także `html`/`body` pod stroną.
 */
export function CareerTheme({
  children,
  page = false,
}: {
  children: React.ReactNode;
  page?: boolean;
}) {
  return (
    <div
      className={`kr-root ${careerDisplayFont.variable} ${careerMonoFont.variable}`}
      lang="pl"
      data-kr-page={page ? "" : undefined}
    >
      {children}
    </div>
  );
}
