FROM artilleryio/artillery:2.0.34@sha256:0d927c76853314d94c6545515821ac98971443301820b93d5193fe2be85780a2

COPY benchmark.yaml /scripts/benchmark.yaml

# <service-name>.<namespace>.svc.cluster.local:<service-port>
COPY start-script.sh /
RUN chmod +x /start-script.sh
ENTRYPOINT [ "/start-script.sh" ]
CMD [ "$SERVICE_URL", "$BENCHMARK_FILE" ]