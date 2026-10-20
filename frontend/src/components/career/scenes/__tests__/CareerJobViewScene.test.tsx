import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CareerJobResponse } from "@/lib/career/api";

import { CareerJobView } from "../../CareerJobView";
import { MUST, NICE } from "./sceneTestUtils";

const job = (theme: string | undefined, must = MUST, nice = NICE): CareerJobResponse => ({
  status: "open",
  theme,
  recruiter: { first_name: "Marta", slug: "marta-n" },
  job: {
    slug: "senior-java-developer-ab12",
    title: "Senior Java Developer",
    subtitle: null,
    about: null,
    must,
    nice,
    params: null,
    show: { must: true, nice: true, params: true, process: true },
  },
});

const view = (data: CareerJobResponse) =>
  render(<CareerJobView data={data} base="/kariera" host="nexus.b2bnetwork.pl" formPreview={{ disableSubmit: true }} />);

describe("strona rekrutacji ze sceną roli", () => {
  it("bez szablonu = Terminal ze sceną i wynikiem przy „Aplikuj”; zwykła lista wymagań zostaje", () => {
    const { container } = view(job(undefined));
    expect(container.querySelector('[data-kr-scene="terminal"]')).not.toBeNull();
    expect(screen.getByRole("link", { name: "Aplikuj — 2 minuty" })).toHaveAttribute("href", "#aplikuj");
    expect(screen.getByText("java_spring_boot")).toBeInTheDocument();
    expect(container.querySelector(".kr-cta-mobile")).toBeNull();
  });

  it("szablon bez gotowej sceny i rekrutacja bez wymagań — strona jak dotąd", () => {
    for (const data of [job("radar"), job("terminal", [], [])]) {
      const { container, unmount } = view(data);
      expect(container.querySelector(".kr-scene")).toBeNull();
      expect(container.querySelector("[data-kr-with-scene]")).toBeNull();
      expect(container.querySelector(".kr-cta-mobile")).not.toBeNull();
      unmount();
    }
  });

  it("wymagania ukryte przez rekrutera nie trafiają do sceny", () => {
    const data = job("sekwencja");
    data.job.show = { must: false, nice: true, params: true, process: true };
    const { container } = view(data);
    expect(container.querySelector(".kr-scene")).toHaveTextContent("kubernetes()");
    expect(container.querySelector(".kr-scene")).not.toHaveTextContent("kafka()");
  });
});
