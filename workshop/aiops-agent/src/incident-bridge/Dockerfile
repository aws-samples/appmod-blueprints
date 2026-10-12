# incident-bridge — minimal SQS->A2A forwarder for the autonomous-remediation demo.
FROM public.ecr.aws/docker/library/python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY poller.py .
# non-root
RUN useradd -u 1000 -m app && chown -R app /app
USER 1000
ENTRYPOINT ["python", "-u", "poller.py"]
