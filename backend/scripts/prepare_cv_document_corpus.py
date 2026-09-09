"""Build synthetic full-CV inputs and a review manifest, without provider calls.

python -m scripts.prepare_cv_document_corpus --output /tmp/cv-document-corpus
This prepares benchmark inputs; it does not score or approve generated CVs.
"""

import argparse
import hashlib
import json
from pathlib import Path

from docx import Document


CORPUS_PATH = Path(__file__).parents[1] / "app/data/cv_quality/full_documents_v2.json"


def load_cases():
    raw = CORPUS_PATH.read_bytes()
    corpus = json.loads(raw)
    cases = corpus["cases"]
    if corpus["schema_version"] != 1 or corpus["synthetic"] is not True:
        raise ValueError("Unsupported corpus")
    if len(cases) != 40 or len({case["id"] for case in cases}) != 40:
        raise ValueError("Expected forty unique variants")
    scenarios = {case["scenario"] for case in cases}
    if len(scenarios) != 20:
        raise ValueError("Expected twenty source scenarios")
    for scenario in scenarios:
        pair = [case for case in cases if case["scenario"] == scenario]
        if {case["language"] for case in pair} != {"pl", "en"}:
            raise ValueError("Missing language pair")
        if pair[0]["cv_paragraphs"] != pair[1]["cv_paragraphs"]:
            raise ValueError("Language variants must use identical sources")
    for case in cases:
        if case["source_format"] not in {"docx_table", "docx_paragraphs"}:
            raise ValueError("Unsupported source format")
        if not case["expected"]["review_criterion"] or len(case["cv_paragraphs"]) < 8:
            raise ValueError("Incomplete source or acceptance criteria")
        if case["expected"]["requires_human_review"] is not True:
            raise ValueError("Human quality review must remain explicit")
    return cases, hashlib.sha256(raw).hexdigest()


def prepare(output: Path):
    cases, digest = load_cases()
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"corpus_sha256": digest, "evaluated": False, "cases": []}
    for case in cases:
        document = Document()
        paragraphs = case["cv_paragraphs"]
        document.add_heading(paragraphs[0], 0)
        if case["source_format"] == "docx_table":
            table = document.add_table(rows=0, cols=1)
            for paragraph in paragraphs[1:]:
                table.add_row().cells[0].text = paragraph
        else:
            for paragraph in paragraphs[1:]:
                document.add_paragraph(paragraph)
        path = output / f"{case['id']}.docx"
        document.save(path)
        manifest["cases"].append(
            {
                **case,
                "input_file": path.name,
                "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "outcome": "not_run",
                "human_accepted": None,
            }
        )
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = prepare(args.output)
    print(
        json.dumps(
            {
                "cases": len(manifest["cases"]),
                "evaluated": False,
                "corpus_sha256": manifest["corpus_sha256"],
            }
        )
    )
