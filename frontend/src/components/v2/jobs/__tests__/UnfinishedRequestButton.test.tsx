/**
 * `UnfinishedRequestButton` — „Dokończ szkic requestu z DD.MM →” na liście
 * `/jobs` (07.11.2026). Najświeższy niedokończony formularz `/jobs/new`,
 * tylko dla osób, które zakładają rekrutacje.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  UnfinishedRequestButton,
  draftDayLabel,
  newestDraft,
} from "@/components/v2/jobs/UnfinishedRequestButton";
import type { IntakeFormListItem } from "@/lib/api/jobIntakeForms";

const getMock = vi.fn();

vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => getMock(...args),
  },
}));

function item(id: number, updatedAt: string, extra: Partial<IntakeFormListItem> = {}) {
  return {
    id,
    label: `Formularz ${id}`,
    client_id: null,
    client_name: null,
    source: "text",
    updated_at: updatedAt,
    expires_at: null,
    ...extra,
  } satisfies IntakeFormListItem;
}

function renderButton(enabled = true) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <UnfinishedRequestButton enabled={enabled} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  getMock.mockReset();
});

describe("draftDayLabel", () => {
  it("liczy dzień w kalendarzu firmy, nie w UTC", () => {
    // 23:30 UTC 04.11 to już 05.11 w Warszawie.
    expect(draftDayLabel("2026-11-04T23:30:00Z")).toBe("05.11");
    expect(draftDayLabel("nie-data")).toBeNull();
  });
});

describe("newestDraft", () => {
  it("bierze ostatnio zmieniany niezależnie od kolejności", () => {
    const list = [
      item(1, "2026-11-01T10:00:00Z"),
      item(2, "2026-11-05T10:00:00Z"),
      item(3, "2026-11-03T10:00:00Z"),
    ];
    expect(newestDraft(list)?.id).toBe(2);
    expect(newestDraft([])).toBeNull();
  });
});

describe("UnfinishedRequestButton", () => {
  it("prowadzi do najświeższego formularza z datą w napisie", async () => {
    getMock.mockResolvedValue({
      data: {
        items: [
          item(7, "2026-11-05T09:00:00Z", { client_name: "Klient Testowy", label: "Java Developer" }),
          item(4, "2026-10-30T09:00:00Z"),
        ],
      },
    });
    renderButton();
    const link = await screen.findByRole("link", { name: /Dokończ szkic requestu z 05\.11/ });
    expect(link).toHaveAttribute("href", "/jobs/new?form=7");
    expect(link).toHaveAttribute(
      "title",
      "Klient Testowy · Java Developer — Pozostałe niedokończone (1) są na „Nowa rekrutacja”.",
    );
    expect(getMock).toHaveBeenCalledWith("/api/job-intake/forms");
  });

  it("bez niedokończonych formularzy nic nie pokazuje", async () => {
    getMock.mockResolvedValue({ data: { items: [] } });
    const { container } = renderButton();
    await vi.waitFor(() => expect(getMock).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("bez uprawnienia do zakładania rekrutacji nie pyta serwera", () => {
    const { container } = renderButton(false);
    expect(getMock).not.toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
  });

  it("awaria zapytania nie udaje szkicu — przycisku po prostu nie ma", async () => {
    getMock.mockRejectedValue(new Error("500"));
    const { container } = renderButton();
    await vi.waitFor(() => expect(getMock).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
