"""Cortex — warstwa „central intelligence" (skill-fact store + widoki).

Moduły:
- ``fact_store``       — normalizacja tokenów przez taksonomię + upserty faktów
- ``extractor_traffit``— backfill faktów z ``cv_extracted_data.traffit_technologie``
- ``tech_map``         — agregat skill × derived-seniority
- ``coverage``         — fill-rates / świeżość / stan procesów (jakość danych)

Kontekst i decyzje: docs/cortex/00-discovery.md.
"""
