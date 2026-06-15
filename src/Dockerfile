FROM python:3.11-slim

WORKDIR /workspace

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
RUN uv sync --all-groups

COPY . .

CMD ["uv", "run", "pytest", "-v"]
