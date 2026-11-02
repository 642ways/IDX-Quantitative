FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY idxquant ./idxquant
COPY run.py .

ENV HOST=0.0.0.0
ENV DATA_PATH=/data/idxquant.sqlite

EXPOSE 8765

CMD ["python", "run.py"]
