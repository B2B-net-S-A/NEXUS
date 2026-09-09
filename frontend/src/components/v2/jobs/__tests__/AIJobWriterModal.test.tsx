import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AIJobWriterModal } from "../AIJobWriterModal";

const generate = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ aiWriterApi: { generateJobDescription: generate } }));

function setup(job: React.ComponentProps<typeof AIJobWriterModal>["job"] = { title: "Developer", requirements: "Python lub Java. Django niewymagane." }) {
  const onUse = vi.fn().mockResolvedValue(undefined);
  const onClose = vi.fn();
  render(<AIJobWriterModal job={job} onUse={onUse} onClose={onClose} />);
  return { onUse, onClose };
}

beforeEach(() => {
  generate.mockReset().mockResolvedValue({ data: { description: "Developer\nPython lub Java. Django niewymagane." } });
});

describe("saved-job factual draft", () => {
  it("does not invent seniority and preserves alternatives and negation", async () => {
    const { onUse } = setup();
    expect(screen.getByRole("button", { name: "Nie podano" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/Szablon na podstawie podanych danych/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Przygotuj szkic" }));
    expect(await screen.findByRole("textbox", { name: "Szkic do sprawdzenia" })).toBeInTheDocument();
    expect(generate).toHaveBeenCalledWith({ title: "Developer", client_name: undefined, seniority: undefined,
      requirements: "Python lub Java. Django niewymagane." });
    expect(onUse).not.toHaveBeenCalled();
  });
  it("prefills an explicit saved level and lets the recruiter clear it", async () => {
    setup({ title: "Developer", seniority: "lead" });
    expect(screen.getByRole("button", { name: "Lead" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Nie podano" }));
    await userEvent.click(screen.getByRole("button", { name: "Przygotuj szkic" }));
    await screen.findByRole("textbox", { name: "Szkic do sprawdzenia" });
    expect(generate.mock.calls[0][0].seniority).toBeUndefined();
  });
  it("treats an unsupported saved level as unspecified", () => {
    setup({ title: "Developer", seniority: "unknown" });
    expect(screen.getByRole("button", { name: "Nie podano" })).toHaveAttribute("aria-pressed", "true");
  });
  it("applies only the edited reviewed description", async () => {
    const { onUse, onClose } = setup();
    await userEvent.click(screen.getByRole("button", { name: "Przygotuj szkic" }));
    await userEvent.clear(await screen.findByRole("textbox", { name: "Szkic do sprawdzenia" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Szkic do sprawdzenia" }), "Sprawdzony opis");
    await userEvent.click(screen.getByRole("button", { name: "Zapisz sprawdzony opis" }));
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(onUse).toHaveBeenCalledExactlyOnceWith("Sprawdzony opis");
  });
  it("keeps the draft and dialog after a failed save and supports retry", async () => {
    const { onUse, onClose } = setup();
    onUse.mockRejectedValueOnce(new Error("save failed"));
    await userEvent.click(screen.getByRole("button", { name: "Przygotuj szkic" }));
    await screen.findByRole("textbox", { name: "Szkic do sprawdzenia" });
    await userEvent.click(screen.getByRole("button", { name: "Zapisz sprawdzony opis" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się zapisać opisu");
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "Szkic do sprawdzenia" })).toHaveValue("Developer\nPython lub Java. Django niewymagane.");
    await userEvent.click(screen.getByRole("button", { name: "Zapisz sprawdzony opis" }));
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  });
  it("requires a new preview when the source criteria change", async () => {
    setup();
    await userEvent.click(screen.getByRole("button", { name: "Przygotuj szkic" }));
    await screen.findByRole("textbox", { name: "Szkic do sprawdzenia" });
    await userEvent.click(screen.getByRole("button", { name: "Mid" }));
    expect(screen.queryByRole("button", { name: "Zapisz sprawdzony opis" })).not.toBeInTheDocument();
  });
});
