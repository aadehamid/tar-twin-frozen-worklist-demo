FROM node:22-slim AS frontend-build
WORKDIR /ui
COPY apps/impactweb/frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY apps/impactweb/frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:python3.12-bookworm
WORKDIR /app
COPY apps/impactweb/backend/pyproject.toml /app/apps/impactweb/backend/pyproject.toml
COPY apps/impactweb/backend/impactweb /app/apps/impactweb/backend/impactweb
COPY --from=frontend-build /backend/impactweb/frontend /app/apps/impactweb/backend/impactweb/frontend
COPY data/scenario /app/data/scenario
RUN uv pip install --system --no-cache fastapi "uvicorn[standard]" sqlmodel psycopg2-binary pydantic
ENV PYTHONPATH=/app/apps/impactweb/backend
ENV SCENARIO_DIR=/app/data/scenario
EXPOSE 8001
CMD ["uvicorn", "impactweb.asgi:app", "--host", "0.0.0.0", "--port", "8001"]
