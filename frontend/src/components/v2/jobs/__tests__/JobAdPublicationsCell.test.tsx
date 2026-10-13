import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { JobAdPublicationsCell, type JobListRowFields } from "@/components/v2/jobs/JobListCells";

const PRACUJ_URL = "https://www.pracuj.pl/praca/przyklad,oferta,1000000001";

function renderCell(job: JobListRowFields, onRowClick = vi.fn()) {
  render(
    // Wiersz listy otwiera rekrutację po kliknięciu — odnośnik nie może tego wywołać.
    <div onClick={onRowClick}>
      <JobAdPublicationsCell job={job} />
    </div>,
  );
  return onRowClick;
}

describe("JobAdPublicationsCell", () => {
  it("rekrutacja bez ogłoszeń pokazuje kreskę", () => {
    renderCell({ ad_publications: [] });
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByTestId("job-ad-publications-cell")).not.toBeInTheDocument();
  });

  it("portale stoją w stałej kolejności, a link otwiera ogłoszenie w nowej karcie", () => {
    const onRowClick = renderCell({
      status: "published",
      ad_publications: [
        { portal: "jjit", url: null, outdated: false },
        { portal: "pracuj", url: PRACUJ_URL, outdated: false },
      ],
    });
    const cell = screen.getByTestId("job-ad-publications-cell");
    expect(cell.textContent).toBe("PracujJJIT");

    const link = screen.getByRole("link", { name: "Pracuj.pl — otwórz ogłoszenie" });
    expect(link).toHaveAttribute("href", PRACUJ_URL);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    fireEvent.click(link);
    expect(onRowClick).not.toHaveBeenCalled();
    // Bez linku plakietka jest zwykłym tekstem.
    expect(screen.queryByRole("link", { name: /JustJoin\.IT/ })).not.toBeInTheDocument();
  });

  it("zmiana treści po publikacji jest nazwana wprost", () => {
    renderCell({
      status: "published",
      ad_publications: [{ portal: "jjit", url: null, outdated: true }],
    });
    expect(
      screen.getByLabelText("JustJoin.IT (treść zmieniła się po publikacji — do aktualizacji)"),
    ).toHaveClass("bg-warning-muted");
  });

  it("zamknięta rekrutacja z wiszącym ogłoszeniem przypomina o zdjęciu", () => {
    renderCell({
      status: "closed",
      ad_publications: [{ portal: "pracuj", url: PRACUJ_URL, outdated: false }],
    });
    expect(
      screen.getByRole("link", {
        name: "Pracuj.pl — otwórz ogłoszenie (rekrutacja zamknięta — zdejmij ogłoszenie z portalu)",
      }),
    ).toHaveClass("bg-warning-muted");
  });

  it("adres, który przeglądarka otworzyłaby poza portalem, nie staje się odnośnikiem", () => {
    renderCell({
      status: "published",
      ad_publications: [
        // Ukośnik wsteczny przeglądarka czyta jak „/”: host to „obca.example”.
        { portal: "pracuj", url: "https://obca.example\\.pracuj.pl/oferta", outdated: false },
        { portal: "jjit", url: "javascript:alert(1)", outdated: false },
      ],
    });
    expect(screen.getByTestId("job-ad-publications-cell").textContent).toBe("PracujJJIT");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
