FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN python3 -m pip install -r requirements.txt
