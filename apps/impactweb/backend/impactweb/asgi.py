"""ASGI entrypoint for running IMPACT Web with uvicorn (impactweb.asgi:app)."""

from impactweb.app import create_app

app = create_app()
