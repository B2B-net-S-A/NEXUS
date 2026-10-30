import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("novelty_guard", ROOT / "scripts/novelty_guard.py")
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)

SCREEN = ["frontend/src/components/jobs/JobBoard.tsx"]
REGISTRY = "backend/app/data/novelties/novelties.json"


class NoveltyGuardTest(unittest.TestCase):
    def test_feat_with_screen_change_and_no_entry_fails(self):
        problem = GUARD.verdict("feat(rekrutacja): nowy przycisk (#1)", "## Po co\nbo tak", SCREEN)
        self.assertIn("novelties.json", problem)
        self.assertIn("Nowość: nie", problem)

    def test_feat_with_registry_entry_passes(self):
        self.assertEqual(GUARD.verdict("feat(rekrutacja): przycisk", "", SCREEN + [REGISTRY]), "")

    def test_opt_out_line_with_reason_passes(self):
        body = "## Zmiany\n- coś\n\nNowość: nie — ekran tylko dla adminów\n"
        self.assertEqual(GUARD.verdict("feat(admin): panel", body, SCREEN), "")

    def test_opt_out_accepts_hyphen_and_lowercase(self):
        self.assertEqual(GUARD.verdict("feat: x", "nowość: nie - poprawka wyglądu", SCREEN), "")

    def test_opt_out_without_reason_fails(self):
        self.assertNotEqual(GUARD.verdict("feat: x", "Nowość: nie", SCREEN), "")
        self.assertNotEqual(GUARD.verdict("feat: x", "Nowość: nie —", SCREEN), "")

    def test_opt_out_must_be_its_own_line(self):
        body = "Napisz „Nowość: nie — powód”, gdy nie ma wpisu."
        self.assertNotEqual(GUARD.verdict("feat: x", body, SCREEN), "")

    def test_non_feat_title_is_ignored(self):
        for title in ("fix(cv): x", "chore(deps): bump", "refactor: y", "docs: z", "Feature request"):
            self.assertEqual(GUARD.verdict(title, "", SCREEN), "", title)

    def test_feat_variants_are_checked(self):
        for title in ("feat: x", "feat(ui): x", "feat!: x", "Feat(UI): x"):
            self.assertNotEqual(GUARD.verdict(title, "", SCREEN), "", title)

    def test_feat_without_screen_change_passes(self):
        files = [
            "backend/app/api/jobs.py",
            "frontend/src/__tests__/jobs.test.tsx",
            "frontend/src/components/jobs/__tests__/Board.test.tsx",
            "frontend/src/lib/format.test.ts",
            "frontend/src/app/preview/jobs/page.tsx",
            "docs/claude/ui/x.md",
        ]
        self.assertEqual(GUARD.verdict("feat(api): nowe pole", "", files), "")

    def test_screen_files_are_app_components_and_lib(self):
        for path in ("frontend/src/app/jobs/page.tsx", "frontend/src/lib/jobs/api.ts", "frontend/src/hooks/useX.ts"):
            self.assertNotEqual(GUARD.verdict("feat: x", "", [path]), "", path)

    def test_none_body_is_empty(self):
        self.assertNotEqual(GUARD.verdict("feat: x", None, SCREEN), "")


if __name__ == "__main__":
    unittest.main()
