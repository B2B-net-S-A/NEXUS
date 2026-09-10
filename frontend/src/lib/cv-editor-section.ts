import { Extension } from "@tiptap/core";

const sections = new Set(["rodo", "why_points", "education", "skills", "certifications", "languages", "experience", "role", "employer", "duties_label", "technologies"]);

/** Keep structural CV markers and consent presentation through real edits. */
export const CvEditorSection = Extension.create({
  name: "cvEditorSection",
  addGlobalAttributes() {
    return [{
      types: ["paragraph", "heading"],
      attributes: {
        cvSection: {
          default: null,
          parseHTML: (element: HTMLElement) => {
            const value = element.dataset.cvSection;
            return value && sections.has(value) ? value : element.classList.contains("rodo") ? "rodo" : null;
          },
          renderHTML: (attributes: Record<string, unknown>) => {
            const value = attributes.cvSection;
            if (typeof value !== "string" || !sections.has(value)) return {};
            return value === "rodo" ? { "data-cv-section": value, style: "font-size: 8pt; line-height: 1.35" } : { "data-cv-section": value };
          },
        },
      },
    }];
  },
});
