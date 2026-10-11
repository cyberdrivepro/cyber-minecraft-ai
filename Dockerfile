# syntax=docker/dockerfile:1
# slim-trixie pinned: ships openjdk-21 in the main archive (needed for Fabric release 21 builds)
FROM python:3.11-slim-trixie

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PORT=7860
ENV HOME=/home/user
ENV PATH="/home/user/.local/bin:${PATH}"

# Install Java 21 (required by Fabric builds targeting release 21), git, curl, unzip
RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-21-jdk-headless \
    git \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Create Hugging Face standard non-root user (UID 1000)
RUN useradd -m -u 1000 user

WORKDIR /app

# Install Python requirements
COPY --chown=user:user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY --chown=user:user . .

# Create and grant permissions on data directories
RUN mkdir -p /data/outputs /data/users && \
    chown -R user:user /data /app

# Switch to non-root user
USER user

# Hugging Face Spaces port
EXPOSE 7860

# Launch FastAPI and Telegram bot
CMD ["python", "main.py"]
