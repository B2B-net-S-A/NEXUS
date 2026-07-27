/**
 * Kontrakt renderowania Markdownu (react-markdown + remark-gfm).
 *
 * Markdown w NEXUS-ie renderuje treści pochodzące od użytkowników (procedury
 * w module Pomoc, `ProcedureEditorModal` / `HelpPageV2`), więc obie rzeczy są
 * tu load-bearing:
 *
 *  1. WYGLĄD — nagłówki, listy, linki, kod i tabele GFM muszą wychodzić jako
 *     te same elementy HTML, bo cała stylizacja opiera się na klasach
 *     `prose-*` z @tailwindcss/typography, które celują w te tagi.
 *  2. BEZPIECZEŃSTWO — call-site'y NIE używają `rehype-raw`, więc surowy HTML
 *     z treści musi zostać odrzucony (brak `<script>`, `<img onerror>`, itd.),
 *     a URL-e `javascript:` muszą być neutralizowane przez domyślny
 *     `urlTransform` react-markdown.
 *
 * Asercja na dokładny HTML (`renders a representative document...`) jest
 * celowo sztywna: to test przypinający zależność. Jeśli bump react-markdown
 * / remark-gfm zmieni wyjście renderera, ten test ma o tym powiedzieć,
 * zanim zmiana trafi na produkcję.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Dokładnie ta konfiguracja, której używają oba miejsca wywołania:
 * `ProcedureEditorModal` (podgląd na żywo) i `HelpPageV2` (widok procedury).
 */
function renderMarkdown(markdown: string) {
  return render(
    <div data-testid="md">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
    </div>,
  );
}

function markdownHtml(markdown: string): string {
  renderMarkdown(markdown);
  return screen.getByTestId("md").innerHTML;
}

describe("renderowanie Markdownu — wygląd", () => {
  it("renders headings as heading elements", () => {
    renderMarkdown("# Tytuł procedury\n\n## Podsekcja");

    expect(
      screen.getByRole("heading", { level: 1, name: "Tytuł procedury" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Podsekcja" }),
    ).toBeInTheDocument();
  });

  it("renders unordered and ordered lists", () => {
    const { container } = renderMarkdown(
      "- pierwszy\n- drugi\n\n1. krok jeden\n2. krok dwa",
    );

    const unordered = container.querySelector("ul");
    const ordered = container.querySelector("ol");

    expect(unordered?.querySelectorAll("li")).toHaveLength(2);
    expect(ordered?.querySelectorAll("li")).toHaveLength(2);
    expect(screen.getByText("krok dwa")).toBeInTheDocument();
  });

  it("renders links with href intact", () => {
    renderMarkdown("[Panel Coolify](https://example.com/panel)");

    const link = screen.getByRole("link", { name: "Panel Coolify" });
    expect(link).toHaveAttribute("href", "https://example.com/panel");
  });

  it("renders inline code and fenced code blocks", () => {
    const { container } = renderMarkdown(
      "Uruchom `npm run build`.\n\n```bash\ndocker compose up -d\n```",
    );

    const inline = screen.getByText("npm run build");
    expect(inline.tagName).toBe("CODE");
    expect(inline.closest("pre")).toBeNull();

    const block = container.querySelector("pre > code");
    expect(block?.textContent).toContain("docker compose up -d");
    expect(block?.className).toContain("language-bash");
  });

  it("renders GFM tables, strikethrough and task lists", () => {
    const { container } = renderMarkdown(
      [
        "| Etap | Status |",
        "| --- | --- |",
        "| Wdrożenie | gotowe |",
        "",
        "~~nieaktualne~~",
        "",
        "- [x] zrobione",
        "- [ ] do zrobienia",
      ].join("\n"),
    );

    expect(container.querySelector("table")).not.toBeNull();
    expect(container.querySelectorAll("th")).toHaveLength(2);
    expect(screen.getByText("Wdrożenie").tagName).toBe("TD");
    expect(container.querySelector("del")?.textContent).toBe("nieaktualne");

    const checkboxes =
      container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
    expect(checkboxes).toHaveLength(2);
    expect(checkboxes[0].checked).toBe(true);
    expect(checkboxes[1].checked).toBe(false);
    // Checkboxy GFM muszą zostać tylko do odczytu — to podgląd, nie formularz.
    expect(checkboxes[0].disabled).toBe(true);
  });

  it("renders a representative document to the exact expected HTML", () => {
    // Test przypinający: dokładne wyjście renderera. Zmiana tego stringa jest
    // dozwolona TYLKO wtedy, gdy świadomie akceptujemy zmianę wyglądu.
    const html = markdownHtml(
      [
        "# Tytuł",
        "",
        "Akapit z **pogrubieniem**, *kursywą* i [linkiem](https://example.com).",
        "",
        "- alfa",
        "- beta",
        "",
        "```ts",
        'const x = 1;',
        "```",
      ].join("\n"),
    );

    expect(html).toBe(
      "<h1>Tytuł</h1>\n" +
        '<p>Akapit z <strong>pogrubieniem</strong>, <em>kursywą</em> i <a href="https://example.com">linkiem</a>.</p>\n' +
        "<ul>\n<li>alfa</li>\n<li>beta</li>\n</ul>\n" +
        '<pre><code class="language-ts">const x = 1;\n</code></pre>',
    );
  });
});

describe("renderowanie Markdownu — bezpieczeństwo (brak rehype-raw)", () => {
  it("does not execute or render raw <script> from content", () => {
    const { container } = renderMarkdown(
      "Przed\n\n<script>window.__pwned = true;</script>\n\nPo",
    );

    expect(container.querySelector("script")).toBeNull();
    expect(container.innerHTML).not.toContain("<script");
    expect(
      (globalThis as Record<string, unknown>).__pwned,
    ).toBeUndefined();
    // Treść wokół wstrzyknięcia nadal się renderuje.
    expect(screen.getByText("Przed")).toBeInTheDocument();
    expect(screen.getByText("Po")).toBeInTheDocument();
  });

  it("does not render raw HTML elements or event-handler attributes", () => {
    const { container } = renderMarkdown(
      [
        '<img src="x" onerror="window.__pwned = true">',
        "",
        '<div onclick="window.__pwned = true">klik</div>',
        "",
        "<b>pogrubione przez HTML</b>",
        "",
        '<iframe src="https://evil.example"></iframe>',
      ].join("\n"),
    );

    const md = screen.getByTestId("md");

    expect(md.querySelector("img")).toBeNull();
    expect(md.querySelector("iframe")).toBeNull();
    expect(md.querySelector("b")).toBeNull();
    // `data-testid` siedzi na jedynym dozwolonym <div> — wewnątrz nie może
    // powstać żaden kolejny z treści.
    expect(md.querySelectorAll("div")).toHaveLength(0);

    // Żaden wyrenderowany element nie może nieść atrybutu obsługi zdarzeń.
    const withHandlers = Array.from(md.querySelectorAll("*")).filter((el) =>
      Array.from(el.attributes).some((attr) =>
        attr.name.toLowerCase().startsWith("on"),
      ),
    );
    expect(withHandlers).toHaveLength(0);
    expect(
      (globalThis as Record<string, unknown>).__pwned,
    ).toBeUndefined();

    // Surowy HTML ląduje jako *zescapowany tekst* (inertny), a nie jako
    // znaczniki — to właśnie zachowanie, które chroni tę ścieżkę bez
    // `rehype-raw`. `container` trzyma go w postaci encji HTML.
    expect(container.innerHTML).toContain("&lt;iframe");
    expect(container.innerHTML).not.toContain("<iframe");
  });

  it("neutralises javascript: URLs in links and images", () => {
    const { container } = renderMarkdown(
      "[kliknij](javascript:window.__pwned=true)\n\n![alt](javascript:window.__pwned=true)",
    );

    const link = container.querySelector("a");
    expect(link).not.toBeNull();
    expect(link?.getAttribute("href")).not.toContain("javascript:");

    const image = container.querySelector("img");
    expect(image?.getAttribute("src") ?? "").not.toContain("javascript:");
    expect(
      (globalThis as Record<string, unknown>).__pwned,
    ).toBeUndefined();
  });

  it("keeps HTML-looking text inside code blocks inert", () => {
    const { container } = renderMarkdown(
      "```html\n<script>alert(1)</script>\n```",
    );

    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("pre > code")?.textContent).toContain(
      "<script>alert(1)</script>",
    );
  });
});
