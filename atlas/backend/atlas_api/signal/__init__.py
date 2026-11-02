"""Signal Mobile backend: asset identity and search, a server-side watchlist, four research agents (news, technical, macro, fundamentals)
and an orchestrator that combines their structured findings. Research only: nothing here places or authorises an order.

Reuses the ATLAS market service, provenance model, technical/MTF analysis, news service, fundamentals service and the macro/Fed Watch services.
Market figures are always computed in code; any AI wording is optional, validated, and may only point at computed facts.
"""
