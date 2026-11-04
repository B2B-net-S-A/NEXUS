import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ImportsSettings } from "../ImportsSettings";

const nav = vi.hoisted(() => ({ params: new URLSearchParams(), replaceUrl: vi.fn() }));

vi.mock("next/navigation", () => ({
  useSearchParams: () => nav.params,
  usePathname: () => "/settings",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));
vi.mock("@/lib/url-selection", () => ({ useUrlWriter: () => ({ replaceUrl: nav.replaceUrl }) }));
vi.mock("@/components/settings/B2BRegisterImportPanel", () => ({
  B2BRegisterImportPanel: () => <div>Panel rejestru z Excela</div>,
}));
vi.mock("@/components/settings/ContractDocsSharePointPanel", () => ({
  ContractDocsSharePointPanel: () => <div>Panel SharePointa</div>,
}));
vi.mock("@/components/settings/TraffitSyncCard", () => ({
  TraffitSyncCard: () => <div>Karta Traffita</div>,
}));

describe("ImportsSettings — importy w jednym miejscu (20.10.2026)", () => {
  beforeEach(() => {
    nav.params = new URLSearchParams("item=imports");
    nav.replaceUrl.mockReset();
  });

  it("bez parametru otwiera rejestr z Excela, zmiana zakładki zostaje w adresie", async () => {
    const user = userEvent.setup();
    render(<ImportsSettings />);
    expect(screen.getByText("Panel rejestru z Excela")).toBeInTheDocument();
    expect(screen.queryByText("Panel SharePointa")).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Dokumenty z SharePointa" }));
    expect(nav.replaceUrl).toHaveBeenCalledWith("/settings?item=imports&zakladka=sharepoint");
  });

  it.each([
    ["sharepoint", "Panel SharePointa"],
    ["traffit", "Karta Traffita"],
    ["cokolwiek", "Panel rejestru z Excela"],
  ])("?zakladka=%s otwiera „%s”", (tab, text) => {
    nav.params = new URLSearchParams(`item=imports&zakladka=${tab}`);
    render(<ImportsSettings />);
    expect(screen.getByText(text)).toBeInTheDocument();
  });
});
