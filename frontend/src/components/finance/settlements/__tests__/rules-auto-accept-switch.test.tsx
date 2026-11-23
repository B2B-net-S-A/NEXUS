import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mutateAsync = vi.fn();
const RULE = {
  key: "order.auto_accept_clean",
  name: "Przyjmuj RCP bez uwag automatycznie",
  level: "off",
  params: { workday: "3" },
  param_fields: [{ key: "workday", label: "od", suffix: "dnia roboczego następnego miesiąca" }],
  hint: null,
  switch: true,
};
const LEVELED = {
  key: "order.charge_on_accept",
  name: "Zejście z zamówienia po przyjęciu RCP",
  level: "block",
  params: {},
  param_fields: [],
  hint: null,
};

// Jeden obiekt na cały test: nowy przy każdym renderze zapętla `useEffect` edytora.
const QUERY = {
  isError: false,
  isSuccess: true,
  data: {
    client_name: "Klient testowy",
    effective_from: "2026-10",
    sections: [{ key: "order", title: "Zamówienie i MD", rules: [RULE, LEVELED] }],
  },
};

vi.mock("@/lib/api/client-settlements", () => ({
  useClientRules: () => QUERY,
  useSaveClientRules: () => ({ mutateAsync, isPending: false }),
  useCopyClientRules: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn(), showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: vi.fn(), confirmDialog: null }),
}));

import { ClientRulesEditor } from "../ClientRulesEditor";

afterEach(() => mutateAsync.mockReset());

describe("Reguły klienta: przełącznik automatu „bez uwag”", () => {
  it("reguła z przełącznikiem nie ma poziomów, włączenie zapisuje `block` z dniem roboczym", async () => {
    mutateAsync.mockResolvedValue({});
    render(<ClientRulesEditor clientId={1} clients={[]} month="2026-11" months={["2026-11"]} canWrite />);
    expect(screen.queryByRole("radiogroup", { name: `Poziom: ${RULE.name}` })).toBeNull();
    expect(screen.getByRole("radiogroup", { name: `Poziom: ${LEVELED.name}` })).toBeTruthy();
    const toggle = screen.getByRole("switch", { name: RULE.name });
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    const rules = mutateAsync.mock.calls[0][0].rules as { key: string; level: string; params: Record<string, string> }[];
    expect(rules.find((r) => r.key === RULE.key)).toEqual({ key: RULE.key, level: "block", params: { workday: "3" } });
  });

  it("bez prawa zapisu przełącznik jest wyłączony", () => {
    render(<ClientRulesEditor clientId={1} clients={[]} month="2026-11" months={["2026-11"]} canWrite={false} />);
    expect((screen.getByRole("switch", { name: RULE.name }) as HTMLButtonElement).disabled).toBe(true);
  });
});
