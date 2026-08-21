import { describe, it, expect, vi } from "vitest";
import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AddClientModal } from "@/components/AppShell";
import api from "@/lib/api";

vi.mock("@/lib/api", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  aiWriterApi: {},
  phase5Api: { clientsLookup: vi.fn() },
  pipelineTemplatesApi: {},
  requestHistoryApi: {},
}));

/**
 * Dwa kontrakty pól formularzy z `AppShell.tsx`, oba regresujące CICHO —
 * aplikacja renderuje się dalej, tylko przestaje być używalna:
 *
 *  1. `FieldGroup` musi spinać `<label htmlFor>` z `id` kontrolki. Bez tego
 *     klik w podpis nie ustawia fokusu, a czytnik ekranu czyta „edycja, puste"
 *     — najdotkliwiej przy `<select>`, gdzie nie ma nawet placeholdera, który
 *     podstawiłby się pod brakującą nazwę.
 *  2. Błąd zapisu z NIE-STRINGOWYM `detail` nie może trafić do stanu
 *     renderowanego jako dziecko Reacta. 503 o wyczerpanej kwocie AI niesie
 *     `{feature, reason, used, limit}`; wpisany wprost wywracał modal przez
 *     error boundary i kasował wypełniony formularz.
 *
 * `AddClientModal` jest najtańszym reprezentantem — wszystkie modale w tym
 * pliku dzielą `FieldGroup`, `ErrorBanner` i ten sam handler błędu.
 */
function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Otwórz
      </button>
      {open && (
        <AddClientModal onClose={() => setOpen(false)} onSuccess={() => {}} />
      )}
    </>
  );
}

async function openModal() {
  const user = userEvent.setup();
  render(<Harness />);
  await user.click(screen.getByRole("button", { name: "Otwórz" }));
  await screen.findByRole("dialog");
  return user;
}

describe("AppShell FieldGroup — dostępna nazwa kontrolki", () => {
  it("spina <label> z <input> przez htmlFor/id", async () => {
    await openModal();

    const input = screen.getByPlaceholderText("Acme Sp. z o.o.");
    expect(input.id).not.toBe("");

    const label = Array.from(document.querySelectorAll("label")).find(
      (el) => el.getAttribute("for") === input.id,
    );
    expect(label?.textContent).toContain("Nazwa firmy");
  });

  it("nazywa <select>, który nie ma placeholdera jako protezy nazwy", async () => {
    await openModal();

    // Ten FieldGroup ma DWOJE dzieci (Select + akapit objaśniający) — id
    // dostaje kontrolka, nie akapit.
    expect(
      screen.getByRole("combobox", { name: /Status handlowy/ }),
    ).toBeInTheDocument();
  });

  it("nadaje różne id kolejnym polom (brak kolizji htmlFor)", async () => {
    await openModal();

    const ids = [
      screen.getByPlaceholderText("Acme Sp. z o.o.").id,
      screen.getByPlaceholderText("IT / Finance...").id,
      screen.getByPlaceholderText("https://firma.pl").id,
    ];
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("AppShell — błąd zapisu z obiektowym detail", () => {
  it("pokazuje `reason` z 503 o kwocie AI zamiast wywracać modal", async () => {
    vi.mocked(api.post).mockRejectedValueOnce({
      response: {
        data: {
          detail: {
            feature: "job_description_generator",
            reason: "Miesięczny limit wyczerpany",
            used: 100,
            limit: 100,
          },
        },
      },
    });
    const user = await openModal();

    await user.type(
      screen.getByPlaceholderText("Acme Sp. z o.o."),
      "Klient testowy",
    );
    await user.click(screen.getByRole("button", { name: "Dodaj firmę" }));

    await waitFor(() =>
      expect(screen.getByText("Miesięczny limit wyczerpany")).toBeInTheDocument(),
    );
    // Formularz przeżył — wypełniona treść jest nadal na ekranie.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Acme Sp. z o.o.")).toHaveValue(
      "Klient testowy",
    );
  });

  it("zamienia 422 z Pydantica na komunikat o polu, nie na tablicę obiektów", async () => {
    vi.mocked(api.post).mockRejectedValueOnce({
      response: {
        data: {
          detail: [
            { loc: ["body", "website"], msg: "invalid URL", type: "value_error" },
          ],
        },
      },
    });
    const user = await openModal();

    await user.type(screen.getByPlaceholderText("Acme Sp. z o.o."), "Klient");
    await user.click(screen.getByRole("button", { name: "Dodaj firmę" }));

    await waitFor(() =>
      expect(screen.getByText("website: invalid URL")).toBeInTheDocument(),
    );
  });
});
