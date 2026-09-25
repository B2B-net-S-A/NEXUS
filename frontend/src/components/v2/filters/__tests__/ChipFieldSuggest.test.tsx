import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { get: (...args: unknown[]) => get(...args) },
  default: { get: (...args: unknown[]) => get(...args) },
}));

import { ChipField } from "@/components/v2/filters/AdvancedSearchPopover";
import { clearKeywordSuggestCache } from "@/lib/keyword-suggest";
import { clearSearchMemory } from "@/lib/search-memory";

const RESPONSE = {
  items: [
    { label: "Java", kind: "skill", insert: "Java", count: 4120 },
    { label: "JavaScript", kind: "skill", insert: "JavaScript", alias: "js", count: 5310 },
  ],
  wildcard: { label: "jav*", kind: "prefix", insert: "jav*", count: 9100 },
};

beforeEach(() => {
  get.mockReset().mockResolvedValue({ data: RESPONSE });
  clearKeywordSuggestCache();
  clearSearchMemory();
});

function renderField(extra: Partial<Parameters<typeof ChipField>[0]> = {}) {
  const onChange = vi.fn();
  render(
    <ChipField
      chips={[]}
      onChange={onChange}
      placeholder="np. Java"
      tone="emerald"
      ariaLabel="Zawiera wszystkie ze słów"
      suggest={{}}
      {...extra}
    />,
  );
  return { onChange, input: screen.getByLabelText("Zawiera wszystkie ze słów") };
}

async function typeAndWait(input: HTMLElement, text: string) {
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: text } });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 250));
  });
  await screen.findAllByRole("option");
}

/** Opcja po treści — pogrubiony początek dzieli tekst na kilka węzłów. */
function option(startsWith: string): HTMLElement {
  const found = screen
    .getAllByRole("option")
    .find((el) => (el.textContent ?? "").startsWith(startsWith));
  if (!found) throw new Error(`brak opcji „${startsWith}”`);
  return found;
}

describe("ChipField z podpowiedziami", () => {
  it("pokazuje listę z bazy z liczbą osób, strzałki wybierają, Enter dodaje", async () => {
    const { onChange, input } = renderField();
    expect(input).toHaveAttribute("role", "combobox");
    await typeAndWait(input, "jav");
    expect(get).toHaveBeenCalledWith(
      "/api/candidates/keywords/suggest",
      expect.objectContaining({ params: { q: "jav", limit: 6 } }),
    );
    expect(screen.getByText(/^~4\s?120$/)).toBeTruthy();
    expect(input).toHaveAttribute("aria-expanded", "true");
    // Nic nie jest zaznaczone, dopóki nie użyjesz strzałki.
    expect(input).not.toHaveAttribute("aria-activedescendant");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith(["JavaScript"]);
  });

  it("Enter bez wyboru strzałką dodaje dokładnie wpisany tekst", async () => {
    const { onChange, input } = renderField();
    await typeAndWait(input, "jav");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith(["jav"]);
  });

  it("nie pokazuje podpowiedzi do poprzedniego słowa, zanim przyjdą nowe", async () => {
    const { onChange, input } = renderField();
    await typeAndWait(input, "jav");
    get.mockReturnValue(new Promise(() => {}));
    fireEvent.change(input, { target: { value: "kafka" } });
    expect(screen.queryByText("JavaScript")).toBeNull();
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith(["kafka"]);
  });

  it("klik w podpowiedź dodaje ją bez dodawania wpisanego tekstu", async () => {
    const { onChange, input } = renderField();
    await typeAndWait(input, "jav");
    fireEvent.mouseDown(option("jav*"));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenLastCalledWith(["jav*"]);
  });

  it("przecinek dodaje dokładnie to, co wpisane, Esc zamyka listę", async () => {
    const { onChange, input } = renderField();
    await typeAndWait(input, "jav");
    fireEvent.keyDown(input, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());
    fireEvent.keyDown(input, { key: "," });
    expect(onChange).toHaveBeenLastCalledWith(["jav"]);
  });

  it("Enter w pustym polu uruchamia wyszukiwanie", () => {
    const onSubmitEmpty = vi.fn();
    const { onChange, input } = renderField({ onSubmitEmpty });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSubmitEmpty).toHaveBeenCalledTimes(1);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("podpowiedzi z rekrutacji są na górze, także bez wpisanego tekstu", async () => {
    const { input } = renderField({ suggest: { context: [{ label: "Kafka", note: "must-have" }] } });
    fireEvent.focus(input);
    expect(await screen.findByText("Z tej rekrutacji")).toBeTruthy();
    expect(option("Kafka")).toBeTruthy();
    expect(get).not.toHaveBeenCalled();
  });

  it("bez `suggest` pole działa jak dotąd, bez zapytań", async () => {
    const onChange = vi.fn();
    render(
      <ChipField chips={[]} onChange={onChange} placeholder="x" tone="rose" ariaLabel="Pole" />,
    );
    const input = screen.getByLabelText("Pole");
    expect(input).not.toHaveAttribute("role", "combobox");
    fireEvent.change(input, { target: { value: "junior" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith(["junior"]);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 250));
    });
    expect(get).not.toHaveBeenCalled();
  });

  it("„z wariantami” dodaje nazwę i jej inne zapisy jednym wyborem", async () => {
    get.mockResolvedValue({
      data: {
        items: [
          {
            label: "Spring Boot",
            kind: "skill",
            insert: "Spring Boot",
            count: 4812,
            variants: ["Springboot"],
          },
        ],
        wildcard: null,
      },
    });
    const { onChange, input } = renderField();
    await typeAndWait(input, "spring");
    fireEvent.mouseDown(option("Spring Boot + Springboot"));
    expect(onChange).toHaveBeenLastCalledWith(["Spring Boot", "Springboot"]);
  });

  it("`|` we wpisanym słowie zamienia się na spację", () => {
    const { onChange, input } = renderField({ suggest: undefined });
    fireEvent.change(input, { target: { value: "React|Vue" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith(["React Vue"]);
  });

  it("układ w linii: słowo „lub” między chipami", () => {
    render(
      <ChipField
        chips={["Kafka", "RabbitMQ"]}
        onChange={() => {}}
        placeholder="lub…"
        tone="emerald"
        ariaLabel="Wiersz"
        layout="inline"
        joiner="lub"
      />,
    );
    expect(screen.getAllByText("lub")).toHaveLength(1);
  });
});

