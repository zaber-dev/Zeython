# Use a lightweight base image
FROM python:3.9-slim-buster

# Zeython image metadata
LABEL org.opencontainers.image.title="Zeython"
LABEL org.opencontainers.image.description="Zeython — Flask MVC Structure with Modular Service Architecture"
LABEL org.opencontainers.image.source="https://github.com/zaber-dev/Zeython"
LABEL org.opencontainers.image.licenses="GPL-3.0-or-later"

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file to the container
COPY requirements.txt .

# Install the required dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code to the container
COPY . .

# Start the modular application (recommended entrypoint)
CMD ["python", "config/application.py"]