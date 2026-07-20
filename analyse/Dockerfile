FROM python:3.11-slim-bullseye

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Install system dependencies for pyodbc / MS SQL and playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg2 \
    apt-transport-https \
    unixodbc-dev \
    g++ \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Add Microsoft repository for SQL Server ODBC driver (Debian 11 - Bullseye)
RUN curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
    && curl https://packages.microsoft.com/config/debian/11/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql17 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy dependency files
COPY requirements.txt pyproject.toml uv.lock* ./

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers and system dependencies
RUN playwright install --with-deps chromium

# Copy application source code
COPY src/ /app/src/
COPY run.py /app/
COPY migrations/ /app/migrations/

# Expose port
EXPOSE 5100

# Run FastAPI app
CMD ["python", "run.py"]
