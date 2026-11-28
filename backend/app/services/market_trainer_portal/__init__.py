"""Wejście trenera z rynku do panelu ``/konsultant`` (0807, decyzje Artura 28.11.2026).

* ``switch`` — własny włącznik ``app_settings['market_trainer_portal']``, niezależny
  od panelu konsultanta; wyłączony = publiczne trasy 404 i żaden mail nie wychodzi;
* ``mail`` — jedyna droga maila do trenera z rynku (włącznik + nadawca panelu);
* ``auth`` — link z maila i sesja trenera (osobne tabele, ``X-Portal-Session``);
* ``panel`` — otwarcie i zamknięcie panelu przez TCM, dane firmy do umowy.

Reguła: ``docs/claude/ludzie/panel-trenera-z-rynku.md``.
"""
