"""Reviewed role-title translations. Never an arbitrary text replacement map."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RoleTranslation:
    en: str
    pl: str


ROLE_TRANSLATIONS = (
    RoleTranslation("Business Analyst", "Analityk Biznesowy"),
    RoleTranslation("System Analyst", "Analityk Systemowy"),
    RoleTranslation("Project Manager", "Kierownik Projektu"),
    RoleTranslation("Software Developer", "Programista"),
    RoleTranslation("Software Tester", "Tester Oprogramowania"),
)


def alias_catalog() -> list[dict[str, str]]:
    return [
        {
            "kind": "role_translation",
            "from": source,
            "to": target,
            "source_language": source_language,
            "target_language": target_language,
        }
        for pair in ROLE_TRANSLATIONS
        for source, target, source_language, target_language in (
            (pair.en, pair.pl, "en", "pl"),
            (pair.pl, pair.en, "pl", "en"),
        )
    ]


def resolve_alias(source: str, target: str) -> dict[str, str] | None:
    return next(
        (
            item
            for item in alias_catalog()
            if item["from"].casefold() == source.strip().casefold()
            and item["to"].casefold() == target.strip().casefold()
        ),
        None,
    )


def accepted_aliases(pairs: tuple[tuple[str, str], ...], language: str):
    return tuple(
        (item["from"], item["to"])
        for source, target in pairs
        if (item := resolve_alias(source, target))
        and item["target_language"] == language
    )


def translate_role_title(title: str, pairs: tuple[tuple[str, str], ...]) -> str:
    # Entire field only. No change in seniority, embedded technology names,
    # qualifications, narrative claims or compound job titles.
    return next(
        (
            target
            for source, target in pairs
            if title.strip().casefold() == source.casefold()
        ),
        title,
    )
