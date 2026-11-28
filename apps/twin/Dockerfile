FROM node:22-slim AS frontend-build
WORKDIR /ui
COPY apps/twin/frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY apps/twin/frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:python3.12-bookworm
WORKDIR /app
COPY apps/twin/backend/pyproject.toml /app/apps/twin/backend/pyproject.toml
COPY apps/twin/backend/twin /app/apps/twin/backend/twin
COPY --from=frontend-build /backend/twin/frontend /app/apps/twin/backend/twin/frontend
COPY data/scenario /app/data/scenario
COPY specs /app/specs
RUN uv pip install --system --no-cache fastapi "uvicorn[standard]" pydantic neo4j pydexpi==2.1.0 lxml pyshacl networkx rdflib httpx rapidfuzz
ENV PYTHONPATH=/app/apps/twin/backend
ENV SCENARIO_DIR=/app/data/scenario
ENV SHAPES_PATH=/app/specs/shapes.ttl
EXPOSE 8000
CMD ["uvicorn", "twin.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
