FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV HOST=0.0.0.0
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p data/uploads data/outputs data/thumbs data/temp
EXPOSE 8080
CMD ["python", "run.py"]
