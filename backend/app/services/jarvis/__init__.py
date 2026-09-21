"""Jarvis — asystent-agent NEXUSA (0330). Opis zasad w ``tools.py`` i CLAUDE.md.

Pakiet celowo nic nie importuje przy starcie: ``app.api.deps`` sięga po
``via_tag``, a pętla agenta (``agent``) importuje ``app.main`` leniwie.
"""
