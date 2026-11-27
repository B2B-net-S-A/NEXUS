/**
 * „Lokalizacja lub tryb pracy” → „Co nie pasuje?” i karta dojazdu (wariant D,
 * 27.11.2026). „Za daleko do biura” nie może zapisać fałszywego „Tylko
 * zdalnie”, a odpowiedzi „Nie pytałem” nie mogą niczego wysłać.
 */

import type * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  default: {
    post: vi.fn().mockResolvedValue({ data: { people: [] } }),
    get: vi.fn().mockResolvedValue({ data: { items: [] } }),
  },
}));

import { RejectionV2 } from "@/components/v2/modals/RejectionV2";
import {
  rejectionWorkModeMoveFields,
  type RejectionWorkModeChoice,
} from "@/components/v2/modals/RejectionWorkModeField";
import { distanceProfileChanges } from "@/components/v2/modals/RejectionWorkModeIssueField";

const reasons = [
  { id: "7", label: "Brak doświadczenia", name: "Brak doświadczenia", applies_to: ["rejected" as const] },
  { id: "9", name: "work_mode_mismatch", label: "Lokalizacja lub tryb pracy", applies_to: ["rejected" as const] },
];

const profileResidence = {
  city: "Kraków",
  country: "PL",
  canonicalCity: "Kraków",
  commute: { officeCities: [], occasionalCommute: null, relocation: null },
};
const profileWorkMode = { modes: ["remote" as const, "hybrid" as const, "onsite" as const], days: 5 };

function renderWindow(props: Partial<React.ComponentProps<typeof RejectionV2>> = {}) {
  const onConfirm = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RejectionV2
        open
        onOpenChange={() => {}}
        terminalType="rejected"
        reasons={reasons}
        previousStageCategory="internal"
        onConfirm={onConfirm}
        workModeJob={{ remotePolicy: "hybrid", onsiteDaysPerWeek: 3 }}
        {...props}
      />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByText("Lokalizacja lub tryb pracy"));
  return onConfirm;
}

const several = {
  jobId: 1,
  people: [
    { candidateId: 1, name: "Anna Przykładowa" },
    { candidateId: 2, name: "Jan Testowy" },
  ],
};

const confirmButton = () => screen.getByRole("button", { name: "Potwierdź" });
const group = (name: string) => screen.getByRole("radiogroup", { name });
const choiceOf = (onConfirm: ReturnType<typeof vi.fn>): RejectionWorkModeChoice =>
  onConfirm.mock.calls[0][8];

describe("RejectionV2 — „Co nie pasuje?” (27.11.2026)", () => {
  it("bez odpowiedzi „Potwierdź” jest zablokowany i nic nie wychodzi", () => {
    const onConfirm = renderWindow();
    expect(screen.getByTestId("rejection-work-mode-issue")).toHaveTextContent("Co nie pasuje?");
    expect(screen.getByText("Ta rekrutacja: hybrydowo · 3 dni w biurze w tygodniu.")).toBeInTheDocument();
    expect(confirmButton()).toBeDisabled();
    fireEvent.click(confirmButton());
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Za daleko do biura"));
    expect(confirmButton()).toBeEnabled();
  });

  it("„Za daleko”: miasto z profilu, reszta „Nie pytałem” — bez dni i bez trybu pracy", () => {
    const onConfirm = renderWindow({ profileResidence, profileWorkMode });
    fireEvent.click(screen.getByText("Za daleko do biura"));
    expect(screen.getByLabelText("Gdzie mieszka?")).toHaveValue("Kraków");
    expect(group("Ile dni w biurze w tych miastach")).toHaveTextContent("Nie pytałem");
    expect(screen.getByTestId("rejection-commute-work-mode")).toHaveTextContent(
      "Tryb pracy na profilu zostaje: Stacjonarnie, hybrydowo lub zdalnie · do 5 dni w biurze w tygodniu.",
    );
    expect(screen.getByTestId("rejection-commute-changes")).toHaveTextContent("Miasto: Kraków bez zmian");
    // Pytanie o dni z gałęzi „Chce mniej dni” się nie pokazuje.
    expect(screen.queryByTestId("rejection-work-mode")).toBeNull();

    fireEvent.click(confirmButton());
    const choice = choiceOf(onConfirm);
    expect(choice).toEqual({
      issue: "distance",
      maxOnsiteDays: null,
      saveToProfile: true,
      residenceCity: "Kraków",
      officeCities: [],
      occasionalCommute: null,
      relocationWilling: null,
      relocationTargets: [],
      acceptsMoreOfficeDays: null,
    });
    expect(rejectionWorkModeMoveFields(choice)).toEqual({
      work_mode_issue: "distance",
      work_mode_save_to_profile: true,
      residence_city: "Kraków",
    });
  });

  it("pod ptaszkiem widać linijka po linijce, co się zmieni na profilu", () => {
    const onConfirm = renderWindow({ profileResidence, profileWorkMode });
    fireEvent.click(screen.getByText("Za daleko do biura"));
    const offices = screen.getByLabelText("Do jakich biur dojedzie");
    fireEvent.change(offices, { target: { value: "Kraków" } });
    fireEvent.keyDown(offices, { key: "Enter" });
    fireEvent.change(screen.getByLabelText("Do jakich biur dojedzie"), { target: { value: "Katowice" } });
    // Wpisane bez Enter też się liczy (wyjście z pola).
    fireEvent.blur(screen.getByLabelText("Do jakich biur dojedzie"));
    // Powtórka (inna wielkość liter) nie dubluje miasta.
    fireEvent.change(screen.getByLabelText("Do jakich biur dojedzie"), { target: { value: "katowice" } });
    fireEvent.keyDown(screen.getByLabelText("Do jakich biur dojedzie"), { key: "Enter" });
    fireEvent.click(within(group("Ile dni w biurze w tych miastach")).getByText("Do 3 dni"));
    fireEvent.click(screen.getByText("Raz w miesiącu tak"));

    const changes = screen.getByTestId("rejection-commute-changes");
    expect(changes).toHaveTextContent("Miasto: Kraków bez zmian");
    expect(changes).toHaveTextContent("Dojedzie do biura: nie uzupełniono → Kraków, Katowice");
    expect(changes).toHaveTextContent("Dni w biurze: do 5 → do 3");
    expect(changes).toHaveTextContent("Dojazd do innego miasta: nie uzupełniono → raz w miesiącu");
    expect(changes).not.toHaveTextContent("Przeprowadzka");
    expect(screen.queryByTestId("rejection-commute-work-mode")).toBeNull();

    fireEvent.click(confirmButton());
    expect(choiceOf(onConfirm)).toMatchObject({
      issue: "distance",
      maxOnsiteDays: 3,
      officeCities: ["Kraków", "Katowice"],
      occasionalCommute: true,
    });
  });

  it("miasto usunięte z listy nie wychodzi", () => {
    const onConfirm = renderWindow({ profileResidence });
    fireEvent.click(screen.getByText("Za daleko do biura"));
    const offices = screen.getByLabelText("Do jakich biur dojedzie");
    fireEvent.change(offices, { target: { value: "Gdańsk" } });
    fireEvent.keyDown(offices, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Usuń miasto: Gdańsk" }));
    fireEvent.click(confirmButton());
    expect(choiceOf(onConfirm).officeCities).toEqual([]);
    expect(rejectionWorkModeMoveFields(choiceOf(onConfirm))).not.toHaveProperty("commute_office_cities");
  });

  it("„Tak, do…” niesie miasta przeprowadzki; „Nie” ich nie wysyła", () => {
    const onConfirm = renderWindow({ profileResidence });
    fireEvent.click(screen.getByText("Za daleko do biura"));
    fireEvent.click(screen.getByText("Tak, do…"));
    const targets = screen.getByLabelText("Dokąd się przeprowadzi");
    fireEvent.change(targets, { target: { value: "Wrocław" } });
    fireEvent.keyDown(targets, { key: "Enter" });
    expect(screen.getByTestId("rejection-commute-changes")).toHaveTextContent(
      "Przeprowadzka: nie uzupełniono → tak: Wrocław",
    );
    fireEvent.click(within(group("Przeprowadzka")).getByText("Nie"));
    fireEvent.click(confirmButton());
    const choice = choiceOf(onConfirm);
    expect(choice).toMatchObject({ relocationWilling: false, relocationTargets: [] });
    expect(rejectionWorkModeMoveFields(choice)).toMatchObject({ relocation_willing: false });
    expect(rejectionWorkModeMoveFields(choice)).not.toHaveProperty("relocation_targets");
  });

  it("wyczyszczone miasto nie wychodzi, a profil bez miasta startuje od pustego pola", () => {
    const onConfirm = renderWindow({
      profileResidence: { city: null, country: null, canonicalCity: null },
    });
    fireEvent.click(screen.getByText("Za daleko do biura"));
    const city = screen.getByLabelText("Gdzie mieszka?");
    expect(city).toHaveValue("");
    fireEvent.change(city, { target: { value: "   " } });
    expect(screen.getByTestId("rejection-commute-changes")).toHaveTextContent("Nic się nie zmieni");
    fireEvent.click(confirmButton());
    expect(choiceOf(onConfirm).residenceCity).toBeNull();
  });

  it("odznaczony zapis chowa listę zmian i idzie jako saveToProfile=false", () => {
    const onConfirm = renderWindow({ profileResidence });
    fireEvent.click(screen.getByText("Za daleko do biura"));
    fireEvent.click(screen.getByRole("checkbox", { name: /Zapisz na profilu kandydata/ }));
    expect(screen.queryByTestId("rejection-commute-changes")).toBeNull();
    fireEvent.click(confirmButton());
    expect(choiceOf(onConfirm)).toMatchObject({ saveToProfile: false, residenceCity: "Kraków" });
  });

  it("„Chce mniej dni”: dni jak dotąd plus zgoda na więcej dni przy wyjątkowym projekcie", () => {
    const onConfirm = renderWindow({ profileWorkMode });
    fireEvent.click(screen.getByText("Chce mniej dni w biurze"));
    const days = group("Ile dni w biurze kandydat akceptuje");
    expect(days).toHaveTextContent("Do 2 dni");
    expect(days).not.toHaveTextContent("Do 3 dni");
    expect(screen.queryByLabelText("Gdzie mieszka?")).toBeNull();
    fireEvent.click(
      within(group("Zgodzi się na więcej dni przy wyjątkowym projekcie")).getByText("Tak"),
    );
    expect(screen.getByTestId("rejection-work-mode-save-extra")).toHaveTextContent(
      "Więcej dni przy wyjątkowym projekcie → tak",
    );
    fireEvent.click(confirmButton());
    const choice = choiceOf(onConfirm);
    expect(choice).toMatchObject({ issue: "office_days", maxOnsiteDays: 0, acceptsMoreOfficeDays: true });
    expect(rejectionWorkModeMoveFields(choice)).toEqual({
      work_mode_issue: "office_days",
      work_mode_max_onsite_days: 0,
      work_mode_save_to_profile: true,
      accepts_more_office_days: true,
    });
  });
});

describe("RejectionV2 — „Co nie pasuje?” przy kilku osobach", () => {
  it("„Za daleko”: bez miasta i list, nic osobistego w ruchu", () => {
    const onConfirm = renderWindow({ emailPreview: several, profileResidence });
    fireEvent.click(screen.getByText("Za daleko do biura"));
    expect(screen.queryByLabelText("Gdzie mieszka?")).toBeNull();
    expect(screen.queryByLabelText("Do jakich biur dojedzie")).toBeNull();
    expect(screen.getByTestId("rejection-commute-several")).toBeInTheDocument();
    fireEvent.click(confirmButton());
    const choice = choiceOf(onConfirm);
    expect(choice).toMatchObject({ issue: "distance", maxOnsiteDays: null, residenceCity: null });
    expect(rejectionWorkModeMoveFields(choice)).toEqual({
      work_mode_issue: "distance",
      work_mode_save_to_profile: true,
    });
  });

  it("„Chce mniej dni”: pytanie o dni zostaje i dni zawsze idą; bez zgody na więcej", () => {
    const onConfirm = renderWindow({ emailPreview: several });
    fireEvent.click(screen.getByText("Chce mniej dni w biurze"));
    expect(group("Ile dni w biurze kandydat akceptuje")).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: "Zgodzi się na więcej dni przy wyjątkowym projekcie" })).toBeNull();
    fireEvent.click(confirmButton());
    expect(choiceOf(onConfirm)).toMatchObject({
      issue: "office_days",
      maxOnsiteDays: 0,
      acceptsMoreOfficeDays: null,
    });
  });
});

describe("rejectionWorkModeMoveFields", () => {
  it("brak wyboru — żadnych pól", () => {
    expect(rejectionWorkModeMoveFields(null)).toEqual({});
    expect(rejectionWorkModeMoveFields(undefined)).toEqual({});
  });

  it("stary kształt (DL, partia QC, formularze bez pytania) — same dni, bez `work_mode_issue`", () => {
    expect(rejectionWorkModeMoveFields({ maxOnsiteDays: 2, saveToProfile: true })).toEqual({
      work_mode_max_onsite_days: 2,
      work_mode_save_to_profile: true,
    });
  });

  it("bez „Co nie pasuje?” pola karty dojazdu nie wychodzą (serwer: 422); puste miasta odpadają", () => {
    expect(
      rejectionWorkModeMoveFields({
        maxOnsiteDays: null,
        saveToProfile: true,
        residenceCity: "Kraków",
        acceptsMoreOfficeDays: true,
      }),
    ).toEqual({ work_mode_save_to_profile: true });
    expect(
      rejectionWorkModeMoveFields({
        issue: "distance",
        maxOnsiteDays: null,
        saveToProfile: true,
        officeCities: [" ", "Gdynia "],
      }),
    ).toEqual({
      work_mode_issue: "distance",
      work_mode_save_to_profile: true,
      commute_office_cities: ["Gdynia"],
    });
  });

  it("miasta przeprowadzki tylko przy „tak”", () => {
    expect(
      rejectionWorkModeMoveFields({
        issue: "distance",
        maxOnsiteDays: null,
        saveToProfile: true,
        relocationWilling: true,
        relocationTargets: ["Wrocław"],
      }),
    ).toMatchObject({ relocation_willing: true, relocation_targets: ["Wrocław"] });
    expect(
      rejectionWorkModeMoveFields({
        issue: "distance",
        maxOnsiteDays: null,
        saveToProfile: true,
        relocationWilling: null,
        relocationTargets: ["Wrocław"],
      }),
    ).not.toHaveProperty("relocation_targets");
  });
});

describe("distanceProfileChanges", () => {
  const base: RejectionWorkModeChoice = {
    issue: "distance",
    maxOnsiteDays: null,
    saveToProfile: true,
    residenceCity: null,
    officeCities: [],
    occasionalCommute: null,
    relocationWilling: null,
    relocationTargets: [],
    acceptsMoreOfficeDays: null,
  };

  it("nowe miasto i nadpisana lista biur pokazują stan przed i po", () => {
    expect(
      distanceProfileChanges(
        { ...base, residenceCity: "Gdańsk", officeCities: ["Gdynia"], maxOnsiteDays: 0 },
        { modes: [], days: null },
        {
          city: "Kraków",
          country: "PL",
          canonicalCity: "Kraków",
          commute: { officeCities: ["Kraków"], occasionalCommute: false, relocation: null },
        },
      ),
    ).toEqual([
      "Miasto: Kraków → Gdańsk",
      "Dojedzie do biura: Kraków → Gdynia",
      "Dni w biurze: nie uzupełniono → tylko zdalnie",
    ]);
  });

  it("profil niewczytany — same nowe wartości", () => {
    expect(
      distanceProfileChanges({ ...base, residenceCity: "Łódź", occasionalCommute: false }, undefined, undefined),
    ).toEqual(["Miasto → Łódź", "Dojazd do innego miasta → nie"]);
  });

  it("same odpowiedzi „Nie pytałem” i puste miasto — pusta lista", () => {
    expect(distanceProfileChanges(base, null, null)).toEqual([]);
  });
});
