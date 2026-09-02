FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# HF Spaces 默认 7860，Render 会注入 PORT
ENV PORT=7860
EXPOSE 7860
CMD gunicorn -w 1 --threads 8 --timeout 120 -b 0.0.0.0:${PORT} app:app
