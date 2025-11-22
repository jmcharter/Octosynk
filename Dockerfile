# Multi-stage build for Octosynk
FROM python:3.13-slim AS builder

# Install UV package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml ./

# Install dependencies
RUN uv pip install --system -r pyproject.toml

# Final stage
FROM python:3.13-slim

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages

# Set working directory
WORKDIR /app

# Copy application code
COPY src/ ./src/
COPY pyproject.toml README.md ./

# Install the application
RUN pip install -e .

# Create non-root user
RUN useradd -m -u 1000 octosynk

# Copy entrypoint script and set permissions
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && \
    chown octosynk:octosynk /entrypoint.sh && \
    chown -R octosynk:octosynk /app

# Switch to non-root user
USER octosynk

# Run entrypoint script (runs once immediately, then keeps container alive)
CMD ["/entrypoint.sh"]
