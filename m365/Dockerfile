FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir httpx fastapi "uvicorn[standard]"
COPY hooks.py /app/
CMD ["uvicorn", "hooks:app", "--host", "0.0.0.0", "--port", "8810"]
