/**
 * Szuflada edycji bloku (04.10.2026): sekcje bloku, zamknięcie z niezapisanymi
 * zmianami pyta, bez zmian zamyka od razu.
 */
import type { ReactNode } from "react";
import { useEffect } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ChampionEditDrawer } from "@/components/champion/ChampionEditDrawer";

const editorProps = vi.fn();
let dirtyOnMount = false;

vi.mock("@/components/ChampionProfileEditor", () => ({
  ChampionProfileEditor: (props: {
    onlySections?: readonly string[];
    layout?: string;
    onDirtyChange?: (d: boolean) => void;
    renderDrawer?: (p: { body: ReactNode; footer: ReactNode }) => ReactNode;
  }) => {
    editorProps(props);
    useEffect(() => {
      if (dirtyOnMount) props.onDirtyChange?.(true);
    }, [props]);
    return <>{props.renderDrawer?.({ body: <p>formularz</p>, footer: <p>stopka</p> })}</>;
  },
}));

function renderDrawer(onClose = vi.fn()) {
  render(<ChampionEditDrawer jobId={7} clientId={3} block="search" canEdit onClose={onClose} />);
  return onClose;
}

describe("ChampionEditDrawer", () => {
  it("pokazuje edytor w układzie szuflady z sekcjami bloku", () => {
    dirtyOnMount = false;
    renderDrawer();
    expect(screen.getByRole("dialog", { name: "Edycja: Czego szukamy" })).toBeInTheDocument();
    expect(screen.getByText("formularz")).toBeInTheDocument();
    expect(screen.getByText("stopka")).toBeInTheDocument();
    const props = editorProps.mock.calls.at(-1)?.[0];
    expect(props.layout).toBe("drawer");
    expect(props.onlySections).toEqual(["stack", "experience", "search"]);
  });

  it("bez zmian Esc zamyka od razu", async () => {
    dirtyOnMount = false;
    const onClose = renderDrawer();
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });

  it("z niezapisanymi zmianami pyta przed zamknięciem; „Wróć do edycji” zostawia szufladę", async () => {
    dirtyOnMount = true;
    const onClose = renderDrawer();
    await userEvent.keyboard("{Escape}");
    expect(await screen.findByText("Zamknąć bez zapisu?")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Wróć do edycji" }));
    expect(onClose).not.toHaveBeenCalled();

    await userEvent.keyboard("{Escape}");
    await userEvent.click(await screen.findByRole("button", { name: "Zamknij bez zapisu" }));
    expect(onClose).toHaveBeenCalled();
  });
});
