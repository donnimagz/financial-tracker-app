FROM python:3.9-slim

WORKDIR /app

# Copy application files
COPY . /app

# Expose port (default 8000, or dynamic PORT env var)
EXPOSE 8000

ENV PORT=8000

CMD ["sh", "-c", "python3 server.py ${PORT}"]
