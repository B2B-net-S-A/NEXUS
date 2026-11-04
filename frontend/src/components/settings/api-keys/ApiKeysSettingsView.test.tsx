import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type {
  ServiceAccountConfigDto,
  ServiceAccountDto,
  ServiceAccountKeyDto,
} from "@/lib/api";

import { ApiKeysSettingsView, type ApiKeysSettingsViewProps } from "./ApiKeysSettingsView";
import type { ApiKeysActions, ApiKeysLoad } from "./types";

const NOW = new Date("2026-10-14T10:00:00Z");
const DAY = 24 * 60 * 60 * 1000;
const at = (days: number) => new Date(NOW.getTime() + days * DAY).toISOString();

const SCOPES = [
  { value: "clients:read", label: "Klienci: odczyt (nazwa, NIP, Delivery Lead)" },
  { value: "md:read", label: "Zużycie MD: odczyt (salda, importy)" },
  { value: "md:write", label: "Zużycie MD: zapis (import, przypisanie wiersza, korekta miesiąca)" },
  { value: "amounts:read", label: "Wszystkie kwoty: także stawki konsultantów, koszty i marża" },
  { value: "traffit:sync", label: "Uruchamianie synchronizacji Traffit" },
];

const CONFIG: ServiceAccountConfigDto = {
  enabled: true,
  default_ttl_days: 90,
  max_ttl_days: 365,
  header: "X-API-Key",
};

function key(over: Partial<ServiceAccountKeyDto>): ServiceAccountKeyDto {
  return {
    key_id: "v2$000000000000000000000001",
    label: "n8n — produkcja",
    created_at: at(-10),
    created_by: 1,
    expires_at: at(60),
    revoked_at: null,
    revoked_by: null,
    revoke_reason: null,
    last_used_at: null,
    last_used_ip: null,
    ...over,
  };
}

function account(over: Partial<ServiceAccountDto> = {}): ServiceAccountDto {
  return {
    id: 1,
    slug: "rozliczenia-n8n",
    name: "Automatyzacja rozliczeń",
    description: null,
    scopes: ["clients:read", "md:write", "amounts:read"],
    is_active: true,
    created_by: 1,
    created_at: at(-100),
    updated_at: at(-1),
    keys: [
      key({}),
      key({ key_id: "v2$000000000000000000000002", label: "Wymiana", expires_at: at(5) }),
      key({
        key_id: "v2$000000000000000000000003",
        label: "Stary skrypt",
        revoked_at: at(-2),
        revoke_reason: "Koniec testów",
      }),
    ],
    ...over,
  };
}

function actionsMock(): { [K in keyof ApiKeysActions]: ReturnType<typeof vi.fn> } & ApiKeysActions {
  return {
    createAccount: vi.fn().mockResolvedValue(undefined),
    updateAccount: vi.fn().mockResolvedValue(undefined),
    deleteAccount: vi.fn().mockResolvedValue(undefined),
    issueKey: vi.fn().mockResolvedValue({
      key: key({ key_id: "v2$000000000000000000000009", label: "Nowy klucz" }),
      api_key: "nxs_v2_000000000000000000000009_PODGLAD-test",
    }),
    revokeKey: vi.fn().mockResolvedValue(undefined),
  } as never;
}

function success(accounts: ServiceAccountDto[], config = CONFIG): ApiKeysLoad {
  return { status: "success", accounts, scopes: SCOPES, config };
}

function renderView(props: Partial<ApiKeysSettingsViewProps> = {}) {
  const actions = actionsMock();
  const onWritesOpenChange = vi.fn();
  const onWebhooksOpenChange = vi.fn();
  render(
    <ApiKeysSettingsView
      load={success([account()])}
      actions={actions}
      writes={{}}
      onWritesOpenChange={onWritesOpenChange}
      webhooks={{}}
      onWebhooksOpenChange={onWebhooksOpenChange}
      now={NOW}
      {...props}
    />,
  );
  return { actions, onWritesOpenChange, onWebhooksOpenChange, user: userEvent.setup() };
}

describe("ApiKeysSettingsView — stany ładowania", () => {
  it("awaria zapytania to komunikat z serwera, nie pusta lista", () => {
    renderView({ load: { status: "error", message: "Serwer nie odpowiada", onRetry: vi.fn() } });
    expect(screen.getByRole("alert")).toHaveTextContent("Serwer nie odpowiada");
    expect(screen.queryByText("Nie ma jeszcze żadnego konta serwisowego")).toBeNull();
    expect(screen.getByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument();
  });

  it("brak uprawnień to osobny komunikat, bez „Spróbuj ponownie”", () => {
    renderView({ load: { status: "error", message: "Tylko administrator.", forbidden: true } });
    expect(screen.getByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Spróbuj ponownie/ })).toBeNull();
  });

  it("ładowanie nie pokazuje pustego stanu", () => {
    renderView({ load: { status: "loading" } });
    expect(screen.getByText("Pobieram konta serwisowe…")).toBeInTheDocument();
    expect(screen.queryByText("Nie ma jeszcze żadnego konta serwisowego")).toBeNull();
  });

  it("pusta lista po sukcesie ma zachętę do założenia konta", async () => {
    const { user } = renderView({ load: success([]) });
    expect(screen.getByText("Nie ma jeszcze żadnego konta serwisowego")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Nowe konto" }));
    expect(screen.getByRole("form", { name: "Nowe konto serwisowe" })).toBeInTheDocument();
  });

  it("ostrzega, gdy klucze są wyłączone na serwerze", () => {
    renderView({ load: success([account()], { ...CONFIG, enabled: false }) });
    expect(screen.getByRole("status")).toHaveTextContent("Klucze API są wyłączone na serwerze");
  });
});

describe("ApiKeysSettingsView — konto i klucze", () => {
  it("pokazuje uprawnienia w grupach i stan każdego klucza", () => {
    renderView();
    const scopes = screen.getByRole("region", { name: "Uprawnienia" });
    expect(within(scopes).getByText("Rozliczenia — odczyt")).toBeInTheDocument();
    expect(within(scopes).getByText("Rozliczenia — zapis")).toBeInTheDocument();
    expect(within(scopes).getByText("Kwoty")).toBeInTheDocument();
    expect(within(scopes).getByText("Zużycie MD: zapis")).toBeInTheDocument();

    const table = screen.getByRole("table", { name: /Klucze konta/ });
    const rows = within(table).getAllByRole("row").slice(1);
    // Aktywne na górze, odwołany na końcu.
    expect(rows.map((r) => within(r).getByRole("rowheader").textContent)).toEqual([
      expect.stringContaining("n8n — produkcja"),
      expect.stringContaining("Wymiana"),
      expect.stringContaining("Stary skrypt"),
    ]);
    expect(within(rows[1]).getByText("Wygasa za 5 dni")).toBeInTheDocument();
    expect(within(rows[0]).queryByText(/Wygasa/)).toBeNull();
    expect(within(rows[2]).getByText("Odwołany")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Powód: Koniec testów")).toBeInTheDocument();
    // Odwołanego nie da się odwołać drugi raz.
    expect(within(rows[2]).queryByRole("button")).toBeNull();
    expect(screen.getByText("2 aktywne klucze")).toBeInTheDocument();
  });

  it("wydany klucz pokazuje się raz, z nagłówkiem, a po zamknięciu znika", async () => {
    const { actions, user } = renderView();
    await user.click(screen.getByRole("button", { name: "Wydaj klucz" }));
    const form = screen.getByRole("form", { name: "Wydaj klucz" });
    // Ważność domyślnie z `/config`.
    expect(within(form).getByLabelText("Ważność (dni)")).toHaveValue("90");
    await user.type(within(form).getByLabelText("Nazwa klucza"), "Nowy klucz");
    await user.click(within(form).getByRole("button", { name: "Wydaj klucz" }));

    expect(actions.issueKey).toHaveBeenCalledWith(1, { label: "Nowy klucz", expires_in_days: 90 });
    const card = await screen.findByRole("region", { name: "Sekret do zapisania" });
    expect(within(card).getByTestId("revealed-secret")).toHaveTextContent(
      "nxs_v2_000000000000000000000009_PODGLAD-test",
    );
    expect(within(card).getByText("X-API-Key")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Wydaj klucz" })).toBeNull();

    await user.click(within(card).getByRole("button", { name: "Zamknij" }));
    expect(screen.queryByRole("region", { name: "Sekret do zapisania" })).toBeNull();
    expect(screen.queryByText(/PODGLAD-test/)).toBeNull();
  });

  it("nie wydaje klucza bez nazwy ani ponad sufit ważności", async () => {
    const { actions, user } = renderView();
    await user.click(screen.getByRole("button", { name: "Wydaj klucz" }));
    const form = screen.getByRole("form", { name: "Wydaj klucz" });
    await user.click(within(form).getByRole("button", { name: "Wydaj klucz" }));
    expect(within(form).getByRole("alert")).toHaveTextContent("Podaj nazwę klucza");

    await user.type(within(form).getByLabelText("Nazwa klucza"), "Za długi");
    const days = within(form).getByLabelText("Ważność (dni)");
    await user.clear(days);
    await user.type(days, "400");
    await user.click(within(form).getByRole("button", { name: "Wydaj klucz" }));
    expect(within(form).getByRole("alert")).toHaveTextContent("Najdłuższa ważność to 365 dni.");
    expect(actions.issueKey).not.toHaveBeenCalled();
  });

  it("błąd wydania klucza pokazuje `detail` z serwera i nie pokazuje sekretu", async () => {
    const { actions, user } = renderView();
    actions.issueKey.mockRejectedValueOnce({
      response: { status: 404, data: { detail: "Konto serwisowe nie istnieje" } },
    });
    await user.click(screen.getByRole("button", { name: "Wydaj klucz" }));
    const form = screen.getByRole("form", { name: "Wydaj klucz" });
    await user.type(within(form).getByLabelText("Nazwa klucza"), "Nowy klucz");
    await user.click(within(form).getByRole("button", { name: "Wydaj klucz" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent("Konto serwisowe nie istnieje");
    expect(screen.queryByRole("region", { name: "Sekret do zapisania" })).toBeNull();
  });

  it("odwołanie pyta o powód w wierszu, potem o potwierdzenie", async () => {
    const { actions, user } = renderView();
    await user.click(screen.getByRole("button", { name: "Odwołaj klucz n8n — produkcja" }));
    const form = screen.getByRole("form", { name: "Odwołanie klucza n8n — produkcja" });
    await user.type(within(form).getByLabelText(/Powód odwołania/), "Wymiana klucza");
    await user.click(within(form).getByRole("button", { name: "Odwołaj klucz" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Odwołać klucz „n8n — produkcja”?");
    await user.click(within(dialog).getByRole("button", { name: "Odwołaj klucz" }));
    expect(actions.revokeKey).toHaveBeenCalledWith(1, "v2$000000000000000000000001", "Wymiana klucza");
  });

  it("anulowane potwierdzenie nie odwołuje klucza; pusty powód idzie jako null", async () => {
    const { actions, user } = renderView();
    await user.click(screen.getByRole("button", { name: "Odwołaj klucz n8n — produkcja" }));
    const form = screen.getByRole("form", { name: "Odwołanie klucza n8n — produkcja" });
    await user.click(within(form).getByRole("button", { name: "Odwołaj klucz" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Anuluj" }));
    expect(actions.revokeKey).not.toHaveBeenCalled();

    await user.click(within(form).getByRole("button", { name: "Odwołaj klucz" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Odwołaj klucz" }));
    expect(actions.revokeKey).toHaveBeenCalledWith(1, "v2$000000000000000000000001", null);
  });

  it("wyłączenie konta wymaga potwierdzenia, włączenie nie", async () => {
    const { actions, user } = renderView();
    await user.click(screen.getByRole("switch", { name: "Konto Automatyzacja rozliczeń aktywne" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Wyłączyć konto „Automatyzacja rozliczeń”?");
    await user.click(within(dialog).getByRole("button", { name: "Anuluj" }));
    expect(actions.updateAccount).not.toHaveBeenCalled();

    await user.click(screen.getByRole("switch", { name: "Konto Automatyzacja rozliczeń aktywne" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Wyłącz konto" }));
    expect(actions.updateAccount).toHaveBeenCalledWith(1, { is_active: false });
  });

  it("włączenie wyłączonego konta idzie bez pytania", async () => {
    const { actions, user } = renderView({ load: success([account({ is_active: false })]) });
    expect(screen.getByText("Wyłączone")).toBeInTheDocument();
    await user.click(screen.getByRole("switch", { name: "Konto Automatyzacja rozliczeń aktywne" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(actions.updateAccount).toHaveBeenCalledWith(1, { is_active: true });
  });

  it("usunięcie konta po potwierdzeniu; błąd serwera zostaje przy koncie", async () => {
    const { actions, user } = renderView();
    actions.deleteAccount.mockRejectedValueOnce({ response: { status: 404, data: { detail: "Konto serwisowe nie istnieje" } } });
    await user.click(screen.getByRole("button", { name: "Usuń konto" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Usuń konto" }));
    expect(actions.deleteAccount).toHaveBeenCalledWith(1);
    expect(await screen.findByText("Konto serwisowe nie istnieje")).toBeInTheDocument();
  });

  it("„Ostatnie zapisy” pytają o dane dopiero po rozwinięciu i pokazują tabelę", async () => {
    const { onWritesOpenChange, user } = renderView({
      writes: {
        1: {
          status: "success",
          writes: [
            {
              id: 7,
              key_id: "v2$000000000000000000000001",
              method: "POST",
              route: "/api/integrations/v1/md/imports",
              state: "done",
              status_code: 201,
              created_at: at(-1),
              completed_at: at(-1),
            },
          ],
        },
      },
    });
    expect(screen.queryByRole("table", { name: /Ostatnie zapisy/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Ostatnie zapisy przez API" }));
    expect(onWritesOpenChange).toHaveBeenCalledWith(1, true);
    const table = screen.getByRole("table", { name: /Ostatnie zapisy/ });
    expect(within(table).getByText("/api/integrations/v1/md/imports")).toBeInTheDocument();
    expect(within(table).getByText("201")).toBeInTheDocument();
    expect(within(table).getByText("Zapisano")).toBeInTheDocument();
    // Klucz po nazwie, nie po identyfikatorze.
    expect(within(table).getByText("n8n — produkcja")).toBeInTheDocument();
  });

  it("awaria „Ostatnich zapisów” to komunikat, nie „nic nie zapisano”", async () => {
    const { user } = renderView({
      writes: { 1: { status: "error", message: "Nie udało się pobrać ostatnich zapisów." } },
    });
    await user.click(screen.getByRole("button", { name: "Ostatnie zapisy przez API" }));
    expect(screen.getByText("Nie udało się pobrać ostatnich zapisów.")).toBeInTheDocument();
    expect(screen.queryByText("To konto nie zapisało jeszcze nic przez API.")).toBeNull();
  });
});

describe("ApiKeysSettingsView — webhooki konta", () => {
  const hook = {
    id: 11,
    url: "https://automatyzacje.example.com/webhook",
    event_types: [] as string[],
    is_active: true,
    last_event_id: 10,
    failure_count: 0,
    next_attempt_at: null,
    disabled_reason: null,
    disabled_at: null,
    last_delivery_at: at(-1),
    last_status: 200,
    last_error: null,
    test_pending: false,
    created_at: at(-7),
  };

  it("pytają o dane dopiero po rozwinięciu i pokazują stan każdego webhooka", async () => {
    const { onWebhooksOpenChange, user } = renderView({
      webhooks: {
        1: {
          status: "success",
          webhooks: [
            hook,
            {
              ...hook,
              id: 12,
              url: "https://stary.example.com/nexus",
              event_types: ["invoice.created"],
              is_active: false,
              disabled_reason: "20 nieudanych prób z rzędu (ostatnio: timeout)",
            },
          ],
        },
      },
    });
    expect(screen.queryByRole("table", { name: /Webhooki konta/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Webhooki" }));
    expect(onWebhooksOpenChange).toHaveBeenCalledWith(1, true);
    const table = screen.getByRole("table", { name: /Webhooki konta/ });
    expect(within(table).getByText("https://automatyzacje.example.com/webhook")).toBeInTheDocument();
    expect(within(table).getByText("Wszystkie dostępne")).toBeInTheDocument();
    expect(within(table).getByText("Działa")).toBeInTheDocument();
    expect(
      within(table).getByText("Wyłączony: 20 nieudanych prób z rzędu (ostatnio: timeout)"),
    ).toBeInTheDocument();
  });

  it("awaria to komunikat, nie „brak webhooków”", async () => {
    const { user } = renderView({
      webhooks: { 1: { status: "error", message: "Nie udało się pobrać webhooków." } },
    });
    await user.click(screen.getByRole("button", { name: "Webhooki" }));
    expect(screen.getByText("Nie udało się pobrać webhooków.")).toBeInTheDocument();
    expect(screen.queryByText(/To konto nie ma webhooków/)).toBeNull();
  });
});

describe("ApiKeysSettingsView — formularz konta", () => {
  it("uprawnienia w grupach po polsku z podpowiedzią o zapisie", async () => {
    const { user } = renderView();
    await user.click(screen.getByRole("button", { name: "Nowe konto" }));
    const form = screen.getByRole("form", { name: "Nowe konto serwisowe" });
    expect(within(form).getByText("Zapis obejmuje odczyt tego samego obszaru.")).toBeInTheDocument();
    const write = within(form).getByRole("group", { name: "Rozliczenia — zapis" });
    expect(within(write).getByRole("checkbox", { name: /Zużycie MD: zapis/ })).toBeInTheDocument();
    const ops = within(form).getByRole("group", { name: "Operacyjne" });
    expect(within(ops).getByRole("checkbox", { name: /Uruchamianie synchronizacji Traffit/ })).toBeInTheDocument();
  });

  it("odrzuca zły slug, a poprawny wysyła znormalizowany z uprawnieniami w kolejności ekranu", async () => {
    const { actions, user } = renderView();
    await user.click(screen.getByRole("button", { name: "Nowe konto" }));
    const form = screen.getByRole("form", { name: "Nowe konto serwisowe" });
    await user.type(within(form).getByLabelText("Identyfikator (slug)"), "zły slug");
    await user.type(within(form).getByLabelText("Nazwa"), "Raport");
    await user.click(within(form).getByRole("button", { name: "Załóż konto" }));
    expect(within(form).getByRole("alert")).toHaveTextContent(/^Identyfikator:/);
    expect(actions.createAccount).not.toHaveBeenCalled();

    const slug = within(form).getByLabelText("Identyfikator (slug)");
    await user.clear(slug);
    await user.type(slug, "Raport-PA");
    await user.click(within(form).getByRole("checkbox", { name: /Zużycie MD: zapis/ }));
    await user.click(within(form).getByRole("checkbox", { name: /Klienci: odczyt/ }));
    await user.click(within(form).getByRole("button", { name: "Załóż konto" }));
    expect(actions.createAccount).toHaveBeenCalledWith({
      slug: "raport-pa",
      name: "Raport",
      description: null,
      scopes: ["clients:read", "md:write"],
    });
  });

  it("zajęty slug (409) pokazuje komunikat serwera w formularzu", async () => {
    const { actions, user } = renderView();
    actions.createAccount.mockRejectedValueOnce({
      response: { status: 409, data: { detail: "Konto serwisowe o slugu 'raport' już istnieje" } },
    });
    await user.click(screen.getByRole("button", { name: "Nowe konto" }));
    const form = screen.getByRole("form", { name: "Nowe konto serwisowe" });
    await user.type(within(form).getByLabelText("Identyfikator (slug)"), "raport");
    await user.type(within(form).getByLabelText("Nazwa"), "Raport");
    await user.click(within(form).getByRole("button", { name: "Załóż konto" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent("już istnieje");
    expect(screen.getByRole("form", { name: "Nowe konto serwisowe" })).toBeInTheDocument();
  });

  it("edycja nie pozwala zmienić slugu i zapisuje nazwę, opis i uprawnienia", async () => {
    const { actions, user } = renderView();
    await user.click(screen.getByRole("button", { name: "Edytuj" }));
    const form = screen.getByRole("form", { name: "Edycja konta serwisowego" });
    expect(within(form).queryByLabelText("Identyfikator (slug)")).toBeNull();
    expect(within(form).getByRole("checkbox", { name: /Klienci: odczyt/ })).toBeChecked();
    await user.click(within(form).getByRole("checkbox", { name: /Klienci: odczyt/ }));
    await user.type(within(form).getByLabelText(/Opis/), "Rozliczenia MD");
    await user.click(within(form).getByRole("button", { name: "Zapisz zmiany" }));
    expect(actions.updateAccount).toHaveBeenCalledWith(1, {
      name: "Automatyzacja rozliczeń",
      description: "Rozliczenia MD",
      scopes: ["md:write", "amounts:read"],
    });
  });
});
