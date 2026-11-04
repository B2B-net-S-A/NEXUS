/**
 * Ustawienia → Wtyczka LinkedIn (makieta 6, 28.10.2026). Dane fikcyjne.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  LinkedinExtensionSettingsView,
  lastUsedLabel,
  usageLabel,
} from "./LinkedinExtensionSettingsView";

const NOW = new Date("2026-10-28T12:00:00+01:00");

const ITEM = {
  key_id: "v1$abc",
  user_id: 7,
  user_name: "Ola Testowa",
  extension_version: "1.0.0",
  created_at: "2026-10-28T08:00:00+01:00",
  expires_at: "2027-04-26T08:00:00+01:00",
  last_used_at: "2026-10-28T11:58:00+01:00",
  reads_today: 34,
  adds_today: 6,
};

describe("lastUsedLabel / usageLabel", () => {
  it("mówi po ludzku, kiedy ostatnio", () => {
    expect(lastUsedLabel(null, NOW)).toBe("jeszcze nie używana");
    expect(lastUsedLabel("2026-10-28T11:58:00+01:00", NOW)).toBe("2 min temu");
    expect(lastUsedLabel("2026-10-28T10:50:00+01:00", NOW)).toBe("1 godz. temu");
    expect(lastUsedLabel("2026-10-27T18:00:00+01:00", NOW)).toBe("wczoraj");
  });

  it("odmienia liczby", () => {
    expect(usageLabel(0, 0)).toBe("—");
    expect(usageLabel(1, 1)).toBe("1 odczyt · 1 dodany");
    expect(usageLabel(34, 2)).toBe("34 odczyty · 2 dodane");
    expect(usageLabel(12, 6)).toBe("12 odczytów · 6 dodanych");
  });
});

describe("LinkedinExtensionSettingsView", () => {
  it("lista połączeń z limitem i odłączeniem po potwierdzeniu", async () => {
    const onRevoke = vi.fn().mockResolvedValue(undefined);
    render(
      <LinkedinExtensionSettingsView
        load={{ status: "success", items: [ITEM], readsLimit: 150 }}
        onRevoke={onRevoke}
        revokingKeyId={null}
        revokeError={null}
        now={NOW}
      />,
    );
    expect(screen.getByText("Ola Testowa")).toBeInTheDocument();
    expect(screen.getByText("34 odczyty · 6 dodanych")).toBeInTheDocument();
    expect(screen.getByText(/limit odczytów stron LinkedIna na osobę: 150/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Odłącz" }));
    await userEvent.click(await screen.findByRole("button", { name: "Odłącz" }));
    expect(onRevoke).toHaveBeenCalledWith("v1$abc");
  });

  it("pusta lista to zachęta, nie błąd", () => {
    render(
      <LinkedinExtensionSettingsView
        load={{ status: "success", items: [], readsLimit: 150 }}
        onRevoke={vi.fn()}
        revokingKeyId={null}
        revokeError={null}
      />,
    );
    expect(screen.getByText(/Nikt jeszcze nie połączył wtyczki/)).toBeInTheDocument();
  });

  it("awaria pobrania nie wygląda jak pusta lista", () => {
    render(
      <LinkedinExtensionSettingsView
        load={{ status: "error", forbidden: false, message: "Nie udało się pobrać połączeń wtyczki.", onRetry: vi.fn() }}
        onRevoke={vi.fn()}
        revokingKeyId={null}
        revokeError={null}
      />,
    );
    expect(screen.getByText("Nie udało się pobrać połączeń wtyczki.")).toBeInTheDocument();
    expect(screen.queryByText(/Nikt jeszcze/)).toBeNull();
  });
});
