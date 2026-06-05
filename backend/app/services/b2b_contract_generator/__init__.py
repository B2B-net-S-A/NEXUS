"""Generator Umów B2B — serwis renderujący umowę (DOCX/HTML) + seed danych.

UWAGA: ten `__init__` celowo NIE importuje pod-modułów (field_mapping/
docx_renderer importują `app.api.contract_templates`, które z kolei importuje
`formatting` z tego pakietu). Pusty init zapobiega cyklowi importów.
"""
