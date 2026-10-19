import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    default: {
      get: vi.fn((url: string) =>
        Promise.resolve({
          data:
            url === "/api/jobs-lookup/search"
              ? {
                  items: [
                    {
                      id: 454,
                      title: "Rekrutacja Testowa",
                      client_id: 3,
                      client_name: "Bank Alfa",
                      status: "open",
                    },
                  ],
                  clients: [{ id: 3, name: "Bank Alfa", jobs_count: 12 }],
                  total: 1,
                }
              : [],
        }),
      ),
    },
  };
});

import { ActiveFilterChips } from "@/components/v2/filters/ActiveFilterChips";
import { DEFAULT_FILTERS, type CandidateFilters } from "@/lib/url-filters";

function renderChips(
  patch: Partial<CandidateFilters>,
  onUpdate = vi.fn(),
  omitKey?: (key: string) => boolean,
  mustRows?: string[][],
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ActiveFilterChips
        filters={{ ...DEFAULT_FILTERS, ...patch }}
        onUpdate={onUpdate}
        omitKey={omitKey}
        mustRows={mustRows}
      />
    </QueryClientProvider>,
  );
  return onUpdate;
}

describe("ActiveFilterChips (UAT B-B06)", () => {
  it("shows the recruitment chip without a client filter, with the title", async () => {
    const onUpdate = renderChips({ recruitmentIds: [454], pipelineStage: ["new"] });
    expect(await screen.findByText("Rekrutacja: Rekrutacja Testowa #454")).toBeInTheDocument();
    expect(screen.getByText("Etap: Nowy")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Usuń filtr: Rekrutacja/ }));
    expect(onUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ recruitmentIds: [], recruitmentMatch: "assigned" }),
    );
  });

  it("blok „Rekrutacje”: chip klienta z kierunkiem i chip trybu bez zakresu", async () => {
    const onUpdate = renderChips({
      recruitmentClientIds: [3],
      recruitmentMatch: "not_assigned",
    });
    expect(await screen.findByText("Poza rekrutacjami klienta: Bank Alfa")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: /Usuń filtr: Poza rekrutacjami klienta/ }),
    );
    // Ostatnia pozycja zakresu zdejmuje filtr — nie zamienia go w „w żadnej rekrutacji”.
    expect(onUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ recruitmentClientIds: [], recruitmentMatch: "assigned" }),
    );
    expect(onUpdate.mock.calls[0][0]).not.toHaveProperty("recruitmentPresence");
  });

  it("blok „Rekrutacje”: tryb bez zakresu ma własny chip", async () => {
    const onUpdate = renderChips({ recruitmentPresence: "never" });
    expect(screen.getByText("Nie brał udziału w żadnej rekrutacji")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Usuń filtr: Nie brał udziału/ }));
    expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({ recruitmentPresence: "" }));
  });

  it("does not hide or duplicate chips nested under other filters", () => {
    renderChips({
      openTo: ["side_projects"],
      recentlyChangedJobs: 2,
      pipelineStage: ["new", "screening"],
    });
    expect(screen.getAllByText("Otwartość: Side-projekty")).toHaveLength(1);
    expect(screen.getAllByText("Zmiana pracy: 2 mies.")).toHaveLength(1);
  });

  it("shows open-to chips without any stage filter", () => {
    renderChips({ openTo: ["side_projects"] });
    expect(screen.getByText("Otwartość: Side-projekty")).toBeInTheDocument();
  });
});

describe("ActiveFilterChips — stawka i lokalizacja (D5/D6, 19.10.2026)", () => {
  it("chip stawki mówi o ukrytych brakach, a ✕ zdejmuje też wybór", async () => {
    const onUpdate = renderChips({ rateMax: 55, hideUnknownRate: true });
    await userEvent.click(
      screen.getByRole("button", {
        name: "Usuń filtr: Stawka: do 55 PLN/h · bez stawki: ukryte",
      }),
    );
    expect(onUpdate).toHaveBeenLastCalledWith(
      expect.objectContaining({ rateMax: null, hideUnknownRate: false }),
    );
  });

  it("kilka miast = jeden chip „Lokalizacja: …”", async () => {
    const onUpdate = renderChips({
      locationPlaces: [
        { city: "Warszawa", radiusKm: 30 },
        { city: "Łódź", radiusKm: null },
        { city: "Kraków", radiusKm: 50 },
      ],
      hideUnknownLocation: true,
    });
    await userEvent.click(
      screen.getByRole("button", {
        name: "Usuń filtr: Lokalizacja: Warszawa +30 km, Łódź, Kraków +50 km · bez miasta: ukryte",
      }),
    );
    expect(onUpdate).toHaveBeenLastCalledWith(
      expect.objectContaining({ locationPlaces: [], location: "", hideUnknownLocation: false }),
    );
  });

  it("jedno miasto po staremu bez zmian", () => {
    renderChips({ location: "Kraków", locationRadiusKm: 25 });
    expect(screen.getByRole("button", { name: "Usuń filtr: 📍 Kraków + 25 km" })).toBeTruthy();
  });
});

describe("ActiveFilterChips — etykiety etapów", () => {
  it("chip etapu „posting” pokazuje etykietę z panelu, nie slug", () => {
    renderChips({ pipelineStage: ["posting", "cv_sent"] });
    expect(screen.getByText("Etap: Ogłoszenia")).toBeInTheDocument();
    expect(screen.getByText("Etap: CV wysłane")).toBeInTheDocument();
    expect(screen.queryByText(/Etap: posting/)).not.toBeInTheDocument();
  });

  it("omitKey chowa chipy pokazane gdzie indziej, a bez pozostałych nic nie rysuje", () => {
    renderChips(
      { rateMax: 160, status: ["active"] },
      vi.fn(),
      (key) => key === "rate",
    );
    expect(screen.queryByText(/Stawka/)).toBeNull();
    expect(screen.getByText("Status: Aktywni")).toBeInTheDocument();
  });

  it("gdy wszystkie chipy są pominięte, nie zostaje samo „Wyczyść wszystko”", () => {
    renderChips({ rateMax: 160 }, vi.fn(), () => true);
    expect(screen.queryByText("Wyczyść wszystko")).toBeNull();
  });

  it("„Mile widziane” miasto i wiersz: usuń albo zamień w filtr (audyt 26.09.2026)", async () => {
    const onUpdate = renderChips({
      locationPreferred: ["Warszawa", "Gdańsk"],
      qPreferred: [["bankow*", "banking"]],
      qAny: [["Java"]],
    });
    expect(screen.getByText("Mile widziane: 📍 Warszawa")).toBeInTheDocument();
    expect(screen.getByText("Mile widziane: bankow* lub banking")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Wymagaj: 📍 Gdańsk" }));
    expect(onUpdate).toHaveBeenLastCalledWith(
      expect.objectContaining({ location: "Gdańsk", locationPreferred: ["Warszawa"] }),
    );

    await userEvent.click(screen.getByRole("button", { name: "Wymagaj: bankow* lub banking" }));
    expect(onUpdate).toHaveBeenLastCalledWith(
      expect.objectContaining({ qAny: [["Java"], ["bankow*", "banking"]], qPreferred: [] }),
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Usuń filtr: Mile widziane: 📍 Warszawa" }),
    );
    expect(onUpdate).toHaveBeenLastCalledWith(
      expect.objectContaining({ locationPreferred: ["Gdańsk"] }),
    );
  });

  it("wiersz „musi mieć” spoza krytycznych ma własną etykietę, „Wymagaj” bez zmian (19.10.2026)", async () => {
    const onUpdate = renderChips(
      {
        qAny: [["SoapUI", "soap ui"]],
        qPreferred: [["Jira", "Xray"], ["ISTQB"], ["kategoria testów"]],
      },
      vi.fn(),
      undefined,
      // Kolejność wariantów i wielkość liter nie mają znaczenia.
      [["xray", "JIRA"], ["ISTQB"]],
    );
    expect(screen.getByText("Musi mieć (DL): Jira lub Xray")).toBeInTheDocument();
    expect(screen.getByText("Musi mieć (DL): ISTQB")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Usuń filtr: Musi mieć (DL): ISTQB" })).toHaveAttribute(
      "title",
      expect.stringContaining("nie wycina"),
    );
    expect(screen.getByText("Mile widziane: kategoria testów")).toBeInTheDocument();
    expect(screen.queryByText("Mile widziane: ISTQB")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Wymagaj: ISTQB" }));
    expect(onUpdate).toHaveBeenLastCalledWith(
      expect.objectContaining({
        qAny: [["SoapUI", "soap ui"], ["ISTQB"]],
        qPreferred: [["Jira", "Xray"], ["kategoria testów"]],
      }),
    );
  });

  it("bez wierszy „musi mieć” (lista poza rekrutacją) wszystko zostaje „Mile widziane”", () => {
    renderChips({ qPreferred: [["ISTQB"]] });
    expect(screen.getByText("Mile widziane: ISTQB")).toBeInTheDocument();
  });

  it("„Mile widziane” kategoria: „Wymagaj” dokłada filtr kategorii", async () => {
    const onUpdate = renderChips({ competenceCategoryPreferred: [5] });
    await userEvent.click(screen.getByRole("button", { name: /^Wymagaj: kategoria/ }));
    expect(onUpdate).toHaveBeenLastCalledWith(
      expect.objectContaining({ competenceCategoryIds: [5], competenceCategoryPreferred: [] }),
    );
  });
});
