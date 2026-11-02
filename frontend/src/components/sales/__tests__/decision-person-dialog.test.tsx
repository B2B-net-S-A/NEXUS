/**
 * Mapa decyzyjna: kto widzi edycję, poprawka wysyła tylko zmienione pola,
 * wartości z kontaktu nie trafiają na mapę, 409 pokazuje komunikat serwera.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AtlasMotion, DecisionMapEntry } from "@/lib/api/sales";

const saveMutate = vi.fn();
const removeMutate = vi.fn();
const showError = vi.fn();
const showSuccess = vi.fn();
const askConfirm = vi.fn();

vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useSaveDecisionPerson: () => ({ mutate: saveMutate, isPending: false }),
  useRemoveDecisionPerson: () => ({ mutate: removeMutate, isPending: false }),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError, showSuccess }) }));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm, confirmDialog: null }),
}));

import { DecisionPersonDialog } from "../DecisionPersonDialog";
import { SalesMotionPanel } from "../SalesMotionPanel";

const entry = (fields: Partial<DecisionMapEntry> = {}): DecisionMapEntry => ({
  key: "k1",
  name: "Osoba Testowa",
  role_in_company: "CTO",
  decision_level: 2,
  contact_status: "not_contacted",
  ...fields,
});
const motion = (people: DecisionMapEntry[]): AtlasMotion =>
  ({ it_factory: { decision_map: people }, meddic: null, products: [], subscription_items: [] }) as AtlasMotion;
const type = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
const save = () => fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

beforeEach(() => {
  saveMutate.mockReset();
  removeMutate.mockReset();
  showError.mockReset();
  askConfirm.mockReset();
});

describe("panel mapy decyzyjnej", () => {
  it("bez uprawnienia do edycji nie ma dodawania ani ołówka", () => {
    render(<SalesMotionPanel opportunityId={1} motion={motion([entry()])} mapEnabled />);
    expect(screen.getByText("Osoba Testowa")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dodaj osobę" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Popraw/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /uzupełnij/ })).toBeNull();
  });

  it("szansa w lejku Fabryki IT bez danych pokazuje pustą mapę z dodawaniem", () => {
    render(<SalesMotionPanel opportunityId={1} motion={null} mapEnabled canEdit />);
    expect(screen.getByText("Na mapie nie ma jeszcze nikogo.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dodaj osobę" }));
    expect(screen.getByText("Dodaj osobę na mapę")).toBeInTheDocument();
  });

  it("szansa spoza lejka bez danych nie pokazuje panelu", () => {
    const { container } = render(<SalesMotionPanel opportunityId={1} motion={null} canEdit />);
    expect(container).toBeEmptyDOMElement();
  });

  it("osoba bez kanału kontaktu ma link do uzupełnienia, który otwiera okno", () => {
    render(<SalesMotionPanel opportunityId={1} motion={motion([entry()])} mapEnabled canEdit />);
    fireEvent.click(screen.getByRole("button", { name: /uzupełnij/ }));
    expect(screen.getByText("Popraw osobę na mapie")).toBeInTheDocument();
    expect(screen.getByLabelText("Imię i nazwisko")).toHaveValue("Osoba Testowa");
  });

  it("po poprawce w NEXUSIE nie mówi już, że dane są z Atlasa", () => {
    const data = motion([entry()]);
    data.it_factory = { ...data.it_factory, updated_at: "2026-09-07T10:00:00Z", nexus_updated_at: "2026-11-02T12:00:00Z" };
    render(<SalesMotionPanel opportunityId={1} motion={data} mapEnabled />);
    expect(screen.getByText(/poprawiona/)).toBeInTheDocument();
    expect(screen.queryByText(/z Atlasa/)).toBeNull();
  });
});

describe("okno osoby na mapie", () => {
  it("nowa osoba bez nazwiska nic nie wysyła", () => {
    render(<DecisionPersonDialog opportunityId={1} entry={null} onClose={() => {}} />);
    save();
    expect(showError).toHaveBeenCalledWith("Wpisz imię i nazwisko.");
    expect(saveMutate).not.toHaveBeenCalled();
  });

  it("nowa osoba wysyła cały formularz, puste pola jako null", () => {
    render(<DecisionPersonDialog opportunityId={1} entry={null} onClose={() => {}} />);
    type("Imię i nazwisko", "  Nowa Osoba ");
    type("Telefon", "+48 500 000 000");
    save();
    expect(saveMutate.mock.calls[0][0]).toEqual({
      key: null,
      payload: {
        name: "Nowa Osoba",
        role_in_company: null,
        decision_level: null,
        our_role: null,
        contact_status: "not_contacted",
        last_contact_at: null,
        phone: "+48 500 000 000",
        email: null,
        linkedin_url: null,
        notes: null,
      },
    });
  });

  it("adres LinkedIn z innym schematem i niepełny mail nie idą do serwera", () => {
    render(<DecisionPersonDialog opportunityId={1} entry={null} onClose={() => {}} />);
    type("Imię i nazwisko", "Nowa Osoba");
    type("LinkedIn", "javascript:alert(1)");
    save();
    expect(showError).toHaveBeenLastCalledWith("Adres LinkedIn musi zaczynać się od http:// albo https://.");
    type("LinkedIn", "linkedin.com/in/osoba");
    type("E-mail", "bez-malpy");
    save();
    expect(showError).toHaveBeenLastCalledWith("Adres e-mail wygląda na niepełny.");
    expect(saveMutate).not.toHaveBeenCalled();
    type("E-mail", "osoba@example.com");
    save();
    expect(saveMutate.mock.calls[0][0].payload).toMatchObject({
      linkedin_url: "linkedin.com/in/osoba",
      email: "osoba@example.com",
    });
  });

  it("poprawka wysyła tylko zmienione pola, a wyczyszczone jako null", () => {
    render(
      <DecisionPersonDialog
        opportunityId={1}
        entry={entry({ notes: "Stara", linkedin_url: "ftp://zly-adres-z-atlasa" })}
        onClose={() => {}}
      />,
    );
    type("Notatka", "Nowa");
    type("Stanowisko", " ");
    save();
    expect(saveMutate.mock.calls[0][0]).toEqual({
      key: "k1",
      payload: { notes: "Nowa", role_in_company: null },
    });
  });

  it("bez zmian zamyka okno i nic nie wysyła", () => {
    const onClose = vi.fn();
    render(<DecisionPersonDialog opportunityId={1} entry={entry()} onClose={onClose} />);
    save();
    expect(onClose).toHaveBeenCalled();
    expect(saveMutate).not.toHaveBeenCalled();
  });

  it("wartość z kontaktu jest podpowiedzią i nie trafia do zapisu", () => {
    render(
      <DecisionPersonDialog
        opportunityId={1}
        entry={entry({ email: "kontakt@example.com", from_contact: ["email"] })}
        onClose={() => {}}
      />,
    );
    const email = screen.getByLabelText("E-mail");
    expect(email).toHaveValue("");
    expect(email).toHaveAttribute("placeholder", "Z kontaktu: kontakt@example.com");
    type("Notatka", "Coś");
    save();
    expect(saveMutate.mock.calls[0][0].payload).toEqual({ notes: "Coś" });
  });

  it("odpowiedź 409 pokazuje komunikat serwera i zostawia okno otwarte", () => {
    const onClose = vi.fn();
    saveMutate.mockImplementation((_input, options) =>
      options.onError({
        response: { status: 409, data: { detail: "Ktoś właśnie zmienił tę osobę na mapie." } },
      }),
    );
    render(<DecisionPersonDialog opportunityId={1} entry={entry()} onClose={onClose} />);
    type("Notatka", "Coś");
    save();
    expect(showError).toHaveBeenCalledWith(expect.stringContaining("Ktoś właśnie zmienił"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("usuwa dopiero po potwierdzeniu", async () => {
    askConfirm.mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    render(<DecisionPersonDialog opportunityId={1} entry={entry()} onClose={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Usuń z mapy" }));
    await waitFor(() => expect(askConfirm).toHaveBeenCalledTimes(1));
    expect(removeMutate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Usuń z mapy" }));
    await waitFor(() => expect(removeMutate).toHaveBeenCalledWith("k1", expect.anything()));
  });
});
