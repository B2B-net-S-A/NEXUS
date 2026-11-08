import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { PublishAllPanel, planPublish, publishOptions } from "@/components/v2/job-ad/PublishAllPanel";

describe("„Opublikuj ogłoszenie” (07.11.2026)", () => {
  it("przy formularzu JJIT strona kariery jest opcjonalna i niezaznaczona", () => {
    const opts = publishOptions({ career: true, careerNeededForJjit: false, jjit: true, pracuj: true });
    expect(opts.map((o) => [o.channel, o.checked])).toEqual([
      ["jjit", true],
      ["pracuj", true],
      ["kariera", false],
    ]);
  });

  it("w trybie linku strona kariery jest zaznaczona razem z JJIT", () => {
    const opts = publishOptions({ career: true, careerNeededForJjit: true, jjit: true, pracuj: false });
    expect(opts.find((o) => o.channel === "kariera")?.checked).toBe(true);
  });

  it("strona kariery bez okna, potem JJIT, potem Pracuj.pl", () => {
    expect(planPublish(["pracuj", "kariera", "jjit"])).toEqual({ career: true, dialogs: ["jjit", "pracuj"] });
    expect(planPublish(["pracuj"])).toEqual({ career: false, dialogs: ["pracuj"] });
  });

  it("jeden kanał do wyboru = bez panelu (wystarczy karta)", () => {
    const opts = publishOptions({ career: false, careerNeededForJjit: false, jjit: true, pracuj: false });
    const { container } = render(<PublishAllPanel options={opts} onStart={vi.fn()} />);
    expect(container.innerHTML).toBe("");
  });

  it("przycisk liczy zaznaczone i oddaje je w kolejności listy", async () => {
    const onStart = vi.fn();
    const opts = publishOptions({ career: true, careerNeededForJjit: false, jjit: true, pracuj: true });
    render(<PublishAllPanel options={opts} onStart={onStart} />);
    expect(screen.getByTestId("publish-all-start").textContent).toBe("Opublikuj na 2 kanałach");

    await userEvent.click(screen.getByTestId("publish-all-kariera"));
    await userEvent.click(screen.getByTestId("publish-all-start"));

    expect(onStart).toHaveBeenCalledWith(["jjit", "pracuj", "kariera"]);
  });
});
