FROM python:3.13-slim
RUN pip install --no-cache-dir "agentmail>=0.1" "httpx>=0.27"
COPY agent.py /app/agent.py
USER 1000:1000
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "/app/agent.py"]
