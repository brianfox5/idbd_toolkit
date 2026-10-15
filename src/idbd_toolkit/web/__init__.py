"""Web client for the IDBD toolkit.

A thin HTTP + browser layer over the SAME core and ToolRegistry the agent toolkit
uses — the second client the architecture was designed for. The browser plugs into
the Interactor seam: INTERACTIVE/CHECKPOINT operations receive their human
answers/confirmations from the request body. No business logic lives here.

Requires the ``web`` dependency group (fastapi, uvicorn). The core never imports it.
"""

from .server import create_app

__all__ = ["create_app"]
