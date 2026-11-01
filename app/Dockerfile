FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends iproute2 iputils-ping && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY nearby ./nearby
ENV NEARBY_DATA=/data
CMD ["uvicorn", "nearby.web:app", "--host", "0.0.0.0", "--port", "8765"]
