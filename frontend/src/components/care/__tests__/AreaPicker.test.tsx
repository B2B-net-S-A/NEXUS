/**
 * „Dział” w panelu osoby („Struktura u klienta”): wpisywanie nazwy nowego
 * działu dotyczy osoby, przy której je zaczęto. Po kliknięciu innej osoby
 * w drzewie pole znika — inaczej „Dodaj” zapisałby dział nie tej osobie.
 * Dane fikcyjne.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn() },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn(), showError: vi.fn() }),
}));
// Radix Select w jsdom nie otwiera listy — natywny <select> o tym samym kontrakcie.
vi.mock("@/components/ui/select", () => ({
  Select: ({
    value,
    onValueChange,
    disabled,
    children,
  }: {
    value: string;
    onValueChange: (next: string) => void;
    disabled?: boolean;
    children: React.ReactNode;
  }) => (
    <select
      data-testid="select"
      value={value}
      disabled={disabled}
      onChange={(event) => onValueChange(event.target.value)}
    >
      {children}
    </select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: React.ReactNode }) => (
    <option value={value}>{children}</option>
  ),
}));

import { PersonPanel } from "@/components/care/PersonPanel";
import { orgPeople } from "@/components/care/client-people-format";
import type { OrgPerson } from "@/lib/api/client-people";
import { clientOrg } from "@/app/preview/hr-client-people/fixtures";

describe("AreaPicker w panelu osoby", () => {
  it("„Nowy dział…” nie przechodzi na inną osobę po zmianie zaznaczenia w drzewie", () => {
    const org = clientOrg("2026-10-19");
    const [first, second] = orgPeople(org);
    const client = new QueryClient();
    const panel = (person: OrgPerson) => (
      <QueryClientProvider client={client}>
        <PersonPanel
          org={org}
          person={person}
          clientId={7001}
          onSelect={() => undefined}
          onFeedback={() => undefined}
        />
      </QueryClientProvider>
    );
    const { rerender } = render(panel(first));
    const area = screen
      .getAllByTestId("select")
      .find((select) => within(select).queryByText("Nowy dział…"));
    expect(area).toBeDefined();
    fireEvent.change(area!, { target: { value: "__new__" } });
    fireEvent.change(screen.getByLabelText("Nazwa nowego działu"), {
      target: { value: "Płatności" },
    });

    rerender(panel(second));
    expect(screen.getByRole("heading", { name: second.name })).toBeInTheDocument();
    expect(screen.queryByLabelText("Nazwa nowego działu")).toBeNull();
  });
});
