"""Web layer: FastAPI API server + SSE + chat (spec P1/P5, M6).

The API server is a separate process from the agent loop. It is read-only over
the data directory except for three writes it is explicitly allowed (spec P5):
the inbox pending queue, chat logs, and ``control/chat.json``. The web UI (M7)
is just one client of this API.
"""
