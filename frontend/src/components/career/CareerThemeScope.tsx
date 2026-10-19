import { careerTheme, themeTokens } from "./themes";

/**
 * Szablon graficzny jednej rekrutacji (0478): nadpisuje zmienne `--kr-*`
 * inline i maluje tło na całą wysokość. Terminal (i brak szablonu) = bez
 * owijki, strona wygląda dokładnie jak przed szablonami.
 */
export function CareerThemeScope({
  theme,
  children,
}: {
  theme?: string | null;
  children: React.ReactNode;
}) {
  const tokens = themeTokens(theme);
  if (Object.keys(tokens).length === 0) return <>{children}</>;
  return (
    <div
      className="kr-scope"
      data-kr-theme={theme ?? undefined}
      data-kr-light={careerTheme(theme).light ? "" : undefined}
      style={tokens as React.CSSProperties}
    >
      {children}
    </div>
  );
}
