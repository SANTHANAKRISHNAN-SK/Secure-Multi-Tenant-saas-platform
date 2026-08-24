# -----------------------------------------------------------------
# Multi-tenant SaaS Flask app - production image for ECS Fargate
# -----------------------------------------------------------------
FROM python:3.12-slim

# Prevent Python from writing .pyc files / buffering stdout,
# which keeps CloudWatch Logs (via the awslogs driver) timely.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install OS packages needed by pymysql / cryptography wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-libmysqlclient-dev gcc pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a non-root user inside the container.
RUN useradd --create-home appuser
USER appuser

EXPOSE 8080

# Gunicorn behind the Application Load Balancer. Tune workers/threads
# to the Fargate task's vCPU allocation.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "3", "--threads", "2", "--timeout", "60", "app:app"]
