"""Jednorazowa naprawa `working-title-prose-fix`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `job_working_title_prose_fix_2026_10` (2026-10-02).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_working_title_prose_fix`.
"""
# Tytuł dla rekrutera bez zdań (02.10.2026) — jednorazowo: przelicz ISTNIEJĄCE
# automatyczne tytuły nową regułą (must-have wpisane zdaniem nie wchodzi do
# tytułu; produkcja miała „… · Minimum 5 lat doświadczenia w an…”). Ręcznych
# tytułów nie rusza i nie podbija `updated_at`. Reguła jest w Pythonie:
# `app/services/job_working_title.py`. Marker w `app_settings` + advisory lock
# → drugi start kończy się od razu. Log i paragon: same liczby.
