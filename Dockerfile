# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PLAYWRIGHT_BROWSERS_PATH=/usr/local/bin/playwright-browsers

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright system dependencies
RUN apt-get update && apt-get install -y \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN useradd -m -u 1000 user
WORKDIR /app

# Install Python dependencies
COPY requirements_hf.txt .
RUN pip install --no-cache-dir -r requirements_hf.txt

# Install Playwright browsers
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy project files
COPY --chown=user:user . .

# Set permissions for the non-root user
RUN chown -R user:user /app
USER user

# Expose port (Hugging Face Spaces use 7860)
EXPOSE 7860

# Start the application with verbose output for debugging
CMD ["sh", "-c", "echo 'Running migrations...' && python manage.py migrate --noinput && echo 'Starting Gunicorn...' && gunicorn config.wsgi:application --bind 0.0.0.0:7860 --workers 1 --threads 4 --timeout 120 --access-logfile - --error-logfile -"]
