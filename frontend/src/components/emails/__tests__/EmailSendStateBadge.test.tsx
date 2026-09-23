import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ microsoft365Api: {} }));
vi.mock("../EmailCompose", () => ({ default: () => null }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ toast: () => {} }) }));

import { SendStateBadge } from "../EmailThreadView";

// FIX-07 (audyt 22.09 r2): wysyłka w toku i wysyłka o nieznanym wyniku
// muszą być widoczne w wątku — inaczej wyglądają jak zwykły wysłany mail.
describe("SendStateBadge", () => {
  it("pokazuje wysyłkę w toku", () => {
    render(<SendStateBadge state="pending" />);
    expect(screen.getByText("Wysyłanie…")).toBeInTheDocument();
  });

  it("każe sprawdzić Wysłane przy nieznanym wyniku", () => {
    render(<SendStateBadge state="uncertain" />);
    expect(
      screen.getByText("Nie wiadomo, czy wyszło — sprawdź Wysłane"),
    ).toBeInTheDocument();
  });

  it("nic nie pokazuje dla wysłanych i zsynchronizowanych", () => {
    const { container: sent } = render(<SendStateBadge state="sent" />);
    expect(sent).toBeEmptyDOMElement();
    const { container: synced } = render(<SendStateBadge state={null} />);
    expect(synced).toBeEmptyDOMElement();
  });
});
