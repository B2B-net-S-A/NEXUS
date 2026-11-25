"""Osoba z pozycji faktury do alertu „bez kontraktu” — sam tekst, bez bazy. Dane fikcyjne."""

from __future__ import annotations

import pytest

from app.services.client_invoicing.unknown_refs import (
    UnknownRef,
    describe,
    marked_people,
    same_person,
)


@pytest.mark.parametrize(
    ("text", "people"),
    [
        (
            "NIDS:2026-000001, IT Retail, Nordea Contact: Ola Kontaktowa, "
            "Contractor Jan Przykładowy ID: M000001",
            ["Jan Przykładowy"],
        ),
        ("Contact:Ola Kontaktowa Contractor Jan Przykładowy ID:M000001", ["Jan Przykładowy"]),
        ("Usługi testerskie, Konsultant: Ewa Testowa, Nr zamówienia 4500000001", ["Ewa Testowa"]),
        ("Inżynier Testów, Konsultant, Adam Próbny Nr zamówienia 1/2026", ["Adam Próbny"]),
        ("Contractor Amina Wanjiru Kip’at ID: M000002", ["Amina Wanjiru Kip’at"]),
        ("Contractor Jan Dwuczłonowy-Nazwisko ID: M3", ["Jan Dwuczłonowy-Nazwisko"]),
        # Bez znacznika osoby nie zgadujemy (nazwy projektów, osoby klienta).
        ("Usługa IT Jan Przykładowy 10/2026", []),
        ("Udostępnienie Konsultanta dla Banku – Jan Przykładowy", []),
        # Osoba klienta wpisana też jako kontraktor to błąd w treści faktury.
        ("Nordea Contact: Ola Kontaktowa, Contractor: Ola Kontaktowa ID: Jan Inny", []),
    ],
)
def test_marked_people(text, people):
    assert marked_people(text) == people


@pytest.mark.parametrize(
    ("contract_person", "invoice_name"),
    [
        ("Jan Przykładowy", "Jan Przykladowy"),
        ("Tomasz Dwuczłonowy-Nazwisko", "Tomasz Dwuczłonowy"),
        ("Tomasz Murawski", "Tomasz Muarwski"),
        ("Amina Wanjiru Kipat", "Amina Wanjiru Kip’at"),
        ("Anna Maria Próbna", "Anna Próbna"),
    ],
)
def test_same_person_despite_shortcut_or_typo(contract_person, invoice_name):
    assert same_person(contract_person, invoice_name)


@pytest.mark.parametrize(
    ("contract_person", "invoice_name"),
    [
        ("Jan Przykładowy", "Piotr Przykładowy"),
        ("Jan Kowal", "Jan Nowakowski"),
        ("Jan", "Jan Przykładowy"),
    ],
)
def test_different_people(contract_person, invoice_name):
    assert not same_person(contract_person, invoice_name)


def test_card_text_names_what_is_missing():
    person = UnknownRef(1, "1/10/2026", 7, 2026, 10, "person", "Jan Przykładowy (ID M1)")
    order = UnknownRef(2, "2/10/2026", 7, 2026, 9, "order", "ORD000001")

    assert "nie ma kontraktu" in describe(person, "Klient")[1]
    assert "10.2026" in describe(person, "Klient")[1]
    assert "ORD000001" in describe(order, "Klient")[1]
    assert person.entity_key == "invoice:1:person:jan-przykladowy-id-m1"
    assert order.entity_key == "invoice:2:order:ord000001"
