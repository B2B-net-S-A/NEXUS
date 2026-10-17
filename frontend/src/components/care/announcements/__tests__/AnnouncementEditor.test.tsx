/**
 * Edytor komunikatu (M7, O12): „Wyślij” dopiero po próbie aktualnej treści,
 * wyłączona wysyłka blokuje wysłanie do kolejki, ale nie do zatwierdzenia ani
 * próby do siebie; nieznane pole w treści blokuje zapis. Dane fikcyjne.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn() }));
vi.mock("@/lib/api", () => ({ api }));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn(), showError: vi.fn() }),
}));

import {
  DRAFT_ID,
  detail,
  options,
  preview,
  settings,
} from "@/app/preview/hr-announcements/fixtures";
import {
  announcementKeys,
  type AnnouncementDetail,
  type AnnouncementSettings,
  type Audience,
} from "@/lib/api/care-announcements";

import { AnnouncementEditor } from "../AnnouncementEditor";

const SMALL: Audience = { group: "client", client_ids: [7001] };

function setup({
  announcement,
  sendingEnabled = true,
}: {
  announcement: AnnouncementDetail | null;
  sendingEnabled?: boolean;
}) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  client.setQueryData(announcementKeys.options, options());
  for (const kind of ["mandatory", "informational"] as const) {
    client.setQueryData(announcementKeys.preview(kind, { group: "all" }), preview());
    client.setQueryData(announcementKeys.preview(kind, SMALL), preview(SMALL));
  }
  const onCreated = vi.fn();
  const view: AnnouncementSettings = settings({ sending_enabled: sendingEnabled });
  render(
    <QueryClientProvider client={client}>
      <AnnouncementEditor
        announcement={announcement}
        settings={view}
        onBack={vi.fn()}
        onCreated={onCreated}
        onSubmitted={vi.fn()}
      />
    </QueryClientProvider>,
  );
  return { onCreated };
}

function draft(overrides: Partial<AnnouncementDetail> = {}): AnnouncementDetail {
  return { ...detail(DRAFT_ID, "author"), subject: "Ankieta o sprzęcie od klienta", ...overrides };
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
});

describe("AnnouncementEditor", () => {
  it("nowy szkic: wysłanie czeka na próbę, próba zakłada szkic i idzie do autora", async () => {
    const user = userEvent.setup();
    const created = draft({ test_current: false, tested_at: null });
    api.post.mockImplementation(async (url: string) => {
      if (url === "/care/announcements") return { data: created };
      if (url === `/care/announcements/${DRAFT_ID}/test-send`) {
        return { data: { ...created, test_current: true } };
      }
      throw new Error(`nieoczekiwane ${url}`);
    });
    const { onCreated } = setup({ announcement: null });

    expect(screen.getByRole("button", { name: "Wyślij do zatwierdzenia" })).toBeDisabled();
    await user.type(screen.getByLabelText("Temat"), "Ankieta o sprzęcie od klienta");
    expect(screen.getByText(/Najpierw wyślij komunikat próbnie/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Wyślij próbnie do mnie" }));
    expect(api.post).toHaveBeenNthCalledWith(
      1,
      "/care/announcements",
      expect.objectContaining({ subject: "Ankieta o sprzęcie od klienta", audience: { group: "all" } }),
    );
    expect(api.post).toHaveBeenNthCalledWith(2, `/care/announcements/${DRAFT_ID}/test-send`);
    expect(onCreated).toHaveBeenCalledWith(DRAFT_ID);
  });

  it("do 20 osób przy wyłączonej wysyłce: „Wyślij” zablokowane, próba działa", () => {
    setup({ announcement: draft({ audience: SMALL }), sendingEnabled: false });
    expect(screen.getByRole("button", { name: "Wyślij" })).toBeDisabled();
    expect(screen.getByText(/Wysyłka do konsultantów jest wyłączona/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Wyślij próbnie do mnie" })).toBeEnabled();
  });

  it("powyżej 20 osób można wysłać do zatwierdzenia mimo wyłączonej wysyłki", () => {
    setup({ announcement: draft(), sendingEnabled: false });
    expect(screen.getByRole("button", { name: "Wyślij do zatwierdzenia" })).toBeEnabled();
    expect(screen.getByText(/powyżej 20 osób/)).toBeInTheDocument();
    expect(screen.getByText("124")).toBeInTheDocument();
  });

  it("zmiana treści po próbie wymaga nowej próby", async () => {
    const user = userEvent.setup();
    setup({ announcement: draft() });
    expect(screen.getByRole("button", { name: "Wyślij do zatwierdzenia" })).toBeEnabled();
    await user.type(screen.getByLabelText("Temat"), " — zmiana");
    expect(screen.getByRole("button", { name: "Wyślij do zatwierdzenia" })).toBeDisabled();
    expect(screen.getByText(/potrzebna po zmianie treści/)).toBeInTheDocument();
  });

  it("nieznane pole w treści blokuje zapis i próbę", async () => {
    const user = userEvent.setup();
    setup({ announcement: draft() });
    const body = screen.getByLabelText("Treść");
    await user.clear(body);
    await user.type(body, "Cześć {{nazwisko}");
    expect(screen.getByText(/Nieznane pole \{nazwisko\}/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Wyślij próbnie do mnie" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Zapisz szkic" })).toBeDisabled();
  });
});
