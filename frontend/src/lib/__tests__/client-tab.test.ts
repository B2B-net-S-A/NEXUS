import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { isClientTab, useClientTab } from "@/lib/client-tab";

describe("useClientTab", () => {
  it("startuje na zakładce z adresu", () => {
    const { result } = renderHook(() => useClientTab("zamowienia"));
    expect(result.current[0]).toBe("zamowienia");
  });

  it("nieznana wartość w adresie nie wywraca strony — wraca profil", () => {
    const { result } = renderHook(() => useClientTab("../etc/passwd"));
    expect(result.current[0]).toBe("profil");
  });

  it("brak parametru = profil", () => {
    const { result } = renderHook(() => useClientTab(null));
    expect(result.current[0]).toBe("profil");
  });

  it("MIĘKKA nawigacja w obrębie tej samej trasy też przełącza zakładkę", () => {
    // To jest sedno: użytkownik JUŻ na /clients/1 klika powiadomienie do
    // /clients/1?tab=zamowienia. App Router zmienia adres, ale komponentu nie
    // odmontowuje, więc sam inicjalizator `useState` by tego nie złapał —
    // stan zostałby na „profil" i link prowadziłby donikąd. Dla Delivery
    // Leada siedzącego na profilu klienta to scenariusz codzienny.
    const { result, rerender } = renderHook(
      ({ tab }: { tab: string | null }) => useClientTab(tab),
      { initialProps: { tab: null as string | null } },
    );
    expect(result.current[0]).toBe("profil");
    rerender({ tab: "zamowienia" });
    expect(result.current[0]).toBe("zamowienia");
  });

  it("ręczne kliknięcie zakładki NIE jest cofane przy kolejnym renderze", () => {
    // Efekt zależy od WARTOŚCI parametru, nie od tożsamości obiektu
    // searchParams — inaczej każdy render przywracałby zakładkę z adresu
    // i ręczne przełączanie byłoby niemożliwe na wejściu z powiadomienia.
    const { result, rerender } = renderHook(
      ({ tab }: { tab: string | null }) => useClientTab(tab),
      { initialProps: { tab: "zamowienia" as string | null } },
    );
    act(() => result.current[1]("analityka"));
    expect(result.current[0]).toBe("analityka");
    rerender({ tab: "zamowienia" });
    expect(result.current[0]).toBe("analityka");
  });

  it("zakładka „zasady” (karta klienta) jest adresowalna — link „Edytuj kartę” ze strony oferty i z Pomocy", () => {
    const { result } = renderHook(() => useClientTab("zasady"));
    expect(result.current[0]).toBe("zasady");
  });
});

describe("isClientTab", () => {
  it("przyjmuje tylko znane zakładki", () => {
    expect(isClientTab("zamowienia")).toBe(true);
    expect(isClientTab("umowy-ramowe")).toBe(true);
    expect(isClientTab("zasady")).toBe(true);
    expect(isClientTab("nie-ma-takiej")).toBe(false);
    expect(isClientTab(null)).toBe(false);
  });
});
