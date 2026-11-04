import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";

describe("QueryStateNotice — odmowa (403)", () => {
  it("domyślny opis mówi o brakującym uprawnieniu i wskazuje, gdzie je nadać — bez słowa o roli", () => {
    render(<QueryStateNotice state="forbidden" />);

    const notice = screen.getByRole("status");
    // Tytuł czytają testy wielu ekranów — zostaje bez zmian.
    expect(notice).toHaveTextContent("Brak uprawnień");
    expect(notice).toHaveTextContent("Nie masz uprawnienia do tych danych.");
    // Odmowa to nie pustka: lista może mieć dane, których konto nie widzi.
    expect(notice).toHaveTextContent("To nie znaczy, że są puste");
    expect(notice).toHaveTextContent(
      "poproś administratora o dostęp (Ustawienia → Zespół i dostęp → Osoby i role)",
    );
    expect(notice).not.toHaveTextContent(/Twoja rola/);
  });

  it("opis ogólny nie obiecuje konkretnego uprawnienia — komponent go nie zna", () => {
    render(<QueryStateNotice state="forbidden" />);

    expect(screen.getByRole("status")).not.toHaveTextContent(/uprawnienia „/);
  });

  it("ekran, który wie, czego brakuje, podaje własny opis z nazwą uprawnienia", () => {
    render(
      <QueryStateNotice
        state="forbidden"
        description="Rejestr wymaga uprawnienia „Klienci, kontrakty i zamówienia: podgląd”."
      />,
    );

    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent(
      "Rejestr wymaga uprawnienia „Klienci, kontrakty i zamówienia: podgląd”.",
    );
    expect(notice).not.toHaveTextContent("Nie masz uprawnienia do tych danych.");
  });

  it("odmowy nie da się „ponowić” — przycisk jest tylko przy awarii", () => {
    const onRetry = vi.fn();
    const forbidden = render(<QueryStateNotice state="forbidden" onRetry={onRetry} />);
    expect(screen.queryByRole("button", { name: /Spróbuj ponownie/ })).toBeNull();
    forbidden.unmount();

    render(<QueryStateNotice state="error" onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Nie udało się pobrać danych");
    fireEvent.click(screen.getByRole("button", { name: /Spróbuj ponownie/ }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
