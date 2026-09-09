import { Extension } from "@tiptap/core";

/** Preserve the consent paragraph's presentation through a real editor edit. */
export const CvEditorSection = Extension.create({
  name: "cvEditorSection",
  addGlobalAttributes() {
    return [{
      types: ["paragraph"],
      attributes: {
        cvSection: {
          default: null,
          parseHTML: (element: HTMLElement) =>
            element.dataset.cvSection === "rodo" || element.classList.contains("rodo")
              ? "rodo" : null,
          renderHTML: (attributes: Record<string, unknown>) => attributes.cvSection === "rodo"
            ? { "data-cv-section": "rodo", style: "font-size: 8pt; line-height: 1.35" } : {},
        },
      },
    }];
  },
});
