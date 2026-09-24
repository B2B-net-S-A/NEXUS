import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  isClientTab,
  positiveIntParam,
  useClientTab,
  useForbiddenTabFallback,
} from "@/lib/client-tab";

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

  it("wybór zakładki zapisuje ją w adresie, a ponowny link do tej samej ?tab= znów przełącza", () => {
    // Zgłoszenie UAT: adres zostawał na zakładce wejścia, więc F5 wracało na
    // nią, a drugi klik w powiadomienie do ?tab=zamowienia (po ręcznym
    // przejściu na Profil) nie zmieniał wartości parametru i nic nie robił.
    const written: string[] = [];
    const { result, rerender } = renderHook(
      ({ tab }: { tab: string | null }) =>
        useClientTab(tab, (next) => written.push(next)),
      { initialProps: { tab: "zamowienia" as string | null } },
    );
    act(() => result.current[2]("profil"));
    expect(result.current[0]).toBe("profil");
    expect(written).toEqual(["profil"]);
    // Strona robi router.replace — adres dogania wybór.
    rerender({ tab: "profil" });
    expect(result.current[0]).toBe("profil");
    // Powiadomienie prowadzi znowu do ?tab=zamowienia — wartość się zmienia.
    rerender({ tab: "zamowienia" });
    expect(result.current[0]).toBe("zamowienia");
  });

  it("wybór zakładki już zapisanej w adresie nie zapisuje adresu drugi raz", () => {
    const written: string[] = [];
    const { result } = renderHook(() =>
      useClientTab("zamowienia", (next) => written.push(next)),
    );
    act(() => result.current[2]("zamowienia"));
    expect(written).toEqual([]);
  });

  it("zakładka „zasady” (karta klienta) jest adresowalna — link „Edytuj kartę” ze strony oferty i z Pomocy", () => {
    const { result } = renderHook(() => useClientTab("zasady"));
    expect(result.current[0]).toBe("zasady");
  });
});

describe("useForbiddenTabFallback", () => {
  it("przed hydracją użytkownika NIE przełącza zakładki z adresu (audyt 24.09, H2)", () => {
    // Pełne wczytanie `/clients/1?tab=umowy-ramowe`: pierwszy render ma
    // `user = null`, więc „brak prawa do Umów” jest jeszcze brakiem wiedzy.
    // Przełączenie na Profil nie było potem cofane.
    const { result, rerender } = renderHook(
      ({ allowed, ready }: { allowed: boolean; ready: boolean }) => {
        const [tab, setTab] = useClientTab("umowy-ramowe");
        useForbiddenTabFallback(tab, setTab, "umowy-ramowe", allowed, ready);
        return tab;
      },
      { initialProps: { allowed: false, ready: false } },
    );
    expect(result.current).toBe("umowy-ramowe");
    rerender({ allowed: true, ready: true });
    expect(result.current).toBe("umowy-ramowe");
  });

  it("po hydracji rola bez prawa trafia na Profil", () => {
    const { result } = renderHook(() => {
      const [tab, setTab] = useClientTab("umowy-ramowe");
      useForbiddenTabFallback(tab, setTab, "umowy-ramowe", false, true);
      return tab;
    });
    expect(result.current).toBe("profil");
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


describe("positiveIntParam", () => {
  it("przyjmuje wyłącznie dodatnie liczby całkowite", () => {
    expect(positiveIntParam("42")).toBe(42);
    for (const bad of [null, "", "0", "-3", "1.5", "abc", "12abc"]) {
      expect(positiveIntParam(bad)).toBeNull();
    }
  });
});
