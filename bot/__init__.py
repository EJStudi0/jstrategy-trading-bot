"""Núcleo nuevo del bot (2026-11).

Una sola lógica de estrategia que usan igual el simulador histórico y el
ejecutor en vivo. El fichero antiguo `04_SCRIPT_BOT_PYTHON.py` tenía tres
implementaciones distintas de la misma estrategia (bucle en vivo, backtest y
`seed_buckets`), y por eso lo que medía el backtest no era lo que operaba el bot.
"""
