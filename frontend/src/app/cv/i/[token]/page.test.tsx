import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import axios from "axios";
import Page from "./page";

vi.mock("next/navigation", () => ({ useParams: () => ({ token: "approved-link" }) }));
vi.mock("axios", () => ({ default: { get: vi.fn(), post: vi.fn() } }));

describe("approved public CV", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
    Element.prototype.scrollTo = vi.fn();
  });

  it("keeps approved HTML while toggling chat and asks through the pinned link", async () => {
    vi.mocked(axios.get).mockResolvedValue({ data: {
      cv: { language: "pl", candidate_name: "Approved", position: "Developer" },
      cv_html: "<p>Approved text only</p>", document_version_id: 71,
      requirements: null, chat_enabled: true, expires_at: null,
    } });
    vi.mocked(axios.post).mockResolvedValue({ data: { answer: "Tylko szkoleniowo." } });
    render(<Page />);
    const frame = await screen.findByTitle("CV");
    expect(frame).toHaveAttribute("srcdoc", "<p>Approved text only</p>");
    expect(screen.getByText("Zapytaj o kandydata")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Podsumuj ostatnią rolę kandydata."));
    await waitFor(() => expect(axios.post).toHaveBeenCalledWith(
      expect.stringContaining("/api/public/cv-i/approved-link/chat"),
      { question: "Podsumuj ostatnią rolę kandydata." },
    ));
    expect(await screen.findByText("Tylko szkoleniowo.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Klasyczne" }));
    expect(screen.queryByText("Zapytaj o kandydata")).not.toBeInTheDocument();
    expect(screen.getByTitle("CV")).toHaveAttribute("srcdoc", "<p>Approved text only</p>");
  });
  it("shows approved evidence next to the exact HTML without jumping to old roles", async () => {
    vi.mocked(axios.get).mockResolvedValue({ data: {
      cv: { language: "pl", candidate_name: "Approved", position: "Developer" },
      cv_html: "<p>AWS tylko szkoleniowo.</p>", document_version_id: 71,
      requirements_status: "complete", chat_enabled: false, expires_at: null,
      requirements: [{ requirement: "AWS", kind: "must", status: "partial", note: null,
        evidence: [{ quote: "AWS tylko szkoleniowo.", experience_index: null }] }],
    } });
    render(<Page />);
    fireEvent.click(await screen.findByRole("button", { name: /AWS/ }));
    expect(screen.getByRole("button", { name: /AWS tylko szkoleniowo/ })).toBeDisabled();
    expect(screen.getByTitle("CV")).toHaveAttribute("srcdoc", "<p>AWS tylko szkoleniowo.</p>");
    fireEvent.click(screen.getByRole("tab", { name: "Klasyczne" }));
    expect(screen.queryByRole("button", { name: /AWS/ })).not.toBeInTheDocument();
  });

  it.each(["queued", "running", "failed", "interrupted", "unavailable"])("explains %s assessment without replacing the CV", async (status) => {
    vi.mocked(axios.get).mockResolvedValue({ data: {
      cv: { language: "en", candidate_name: "Approved", position: "Developer" },
      cv_html: "<p>Approved</p>", document_version_id: 71,
      requirements: [], requirements_status: status, chat_enabled: false, expires_at: null,
    } });
    render(<Page />);
    expect(await screen.findByRole("status")).toHaveTextContent(
      ["queued", "running"].includes(status) ? "being prepared" : "unavailable",
    );
    expect(screen.getByTitle("CV")).toHaveAttribute("srcdoc", "<p>Approved</p>");
    expect(axios.get).toHaveBeenCalledTimes(1);
  });


  const approvedHtml = { data: {
    cv: { language: "pl", candidate_name: "Approved", position: "Developer" },
    cv_html: "<p>Approved</p>", document_version_id: 71,
    requirements: null, chat_enabled: true, expires_at: null,
  } };

  it("prints the whole approved CV frame, not the page clipping it", async () => {
    vi.mocked(axios.get).mockResolvedValue(approvedHtml);
    const pagePrint = vi.spyOn(window, "print").mockImplementation(() => {});
    render(<Page />);
    const frame = (await screen.findByTitle("CV")) as HTMLIFrameElement;
    expect(frame.getAttribute("sandbox")).toContain("allow-modals");
    expect(frame.getAttribute("sandbox")).not.toContain("allow-scripts");
    const framePrint = vi.fn();
    Object.defineProperty(frame, "contentWindow", {
      configurable: true, value: { focus: vi.fn(), print: framePrint },
    });
    Object.defineProperty(frame, "contentDocument", {
      configurable: true, value: { documentElement: { scrollHeight: 1417 } },
    });
    fireEvent.load(frame);
    await waitFor(() => expect(frame.style.height).toBe("1417px"));
    fireEvent.click(screen.getByRole("button", { name: /Drukuj/ }));
    expect(framePrint).toHaveBeenCalledTimes(1);
    expect(pagePrint).not.toHaveBeenCalled();
    pagePrint.mockRestore();
  });

  it("prints the page when there is no approved frame", async () => {
    vi.mocked(axios.get).mockResolvedValue({ data: {
      cv: { language: "pl", candidate_name: "Legacy", position: "Developer", why_points: [],
        education: [], skills: [], certifications: [], languages: [], experience: [] },
      cv_html: null, requirements: null, chat_enabled: false, expires_at: null,
    } });
    const pagePrint = vi.spyOn(window, "print").mockImplementation(() => {});
    render(<Page />);
    fireEvent.click(await screen.findByRole("button", { name: /Drukuj/ }));
    expect(pagePrint).toHaveBeenCalledTimes(1);
    pagePrint.mockRestore();
  });

  it("explains a chat timeout instead of a generic failure", async () => {
    vi.mocked(axios.get).mockResolvedValue(approvedHtml);
    vi.mocked(axios.post).mockRejectedValue({ response: { status: 504, data: {} } });
    render(<Page />);
    fireEvent.click(await screen.findByText("Podsumuj ostatnią rolę kandydata."));
    expect(await screen.findByText(/nie odpowiedział na czas/)).toBeInTheDocument();
  });
});
