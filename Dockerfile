FROM mcr.microsoft.com/playwright/python:v1.52.0

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple

COPY src/ ./src/

WORKDIR /app/src
CMD ["python", "run.py"]
