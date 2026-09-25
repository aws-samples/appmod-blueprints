# a2a-chat-ui — generic Keycloak-gated A2A chat front-end for an OAP Strands agent
FROM python:3.12-slim
WORKDIR /app
RUN groupadd -r app && useradd -r -g app app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
COPY static/ ./static/
ENV PORT=8080
EXPOSE 8080
USER app
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
