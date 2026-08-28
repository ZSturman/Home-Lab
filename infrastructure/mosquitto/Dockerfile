FROM eclipse-mosquitto:2.0.22

COPY --chmod=755 homeplatform-entrypoint.sh /usr/local/bin/homeplatform-entrypoint

ENTRYPOINT ["/usr/local/bin/homeplatform-entrypoint"]
CMD ["/usr/sbin/mosquitto", "-c", "/mosquitto/config/mosquitto.conf"]
