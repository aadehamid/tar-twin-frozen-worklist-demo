"""ASGI entrypoint for running the Unit 200 Digital Twin service with uvicorn (twin.asgi:app)."""

from twin.app import create_app

app = create_app()
