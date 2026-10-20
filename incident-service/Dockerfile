# syntax=docker/dockerfile:1
# incident-service: multi-stage build -> small JRE image running as a non-root user.
# All configuration comes from environment variables at runtime (DB_URL, DB_PASSWORD, JWT_SECRET,
# INTERNAL_API_TOKEN, ...; see .env.example). Nothing secret is baked into any layer.

# ---------------------------------------------------------------- build
FROM eclipse-temurin:17.0.20.1_1-jdk-noble AS build
WORKDIR /workspace

# 1) Maven wrapper + pom only: the dependency download is its own layer and stays cached until pom.xml
#    changes. (mvnw is stored in git without the executable bit, hence --chmod.)
COPY --chmod=755 mvnw ./
COPY .mvn .mvn
COPY pom.xml ./
RUN ./mvnw -B -ntp dependency:go-offline

# 2) Sources, then the jar. Tests are skipped here: CI runs them in the java job before images are built.
COPY src src
RUN ./mvnw -B -ntp package -DskipTests \
    && cp target/incident-service-*.jar application.jar

# 3) Split the fat jar into layers (Spring Boot 4: -Djarmode=tools; "layertools" no longer exists):
#    dependencies change rarely, the application layer on every commit, so pushes stay small.
RUN java -Djarmode=tools -jar application.jar extract --layers --destination extracted

# ---------------------------------------------------------------- runtime
FROM eclipse-temurin:17.0.20.1_1-jre-noble

# Unprivileged user with a fixed uid (same uid as the worker image), no login shell, no home needed.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app

# Least-changing layer first.
COPY --from=build /workspace/extracted/dependencies/ ./
COPY --from=build /workspace/extracted/spring-boot-loader/ ./
COPY --from=build /workspace/extracted/snapshot-dependencies/ ./
COPY --from=build /workspace/extracted/application/ ./

USER 10001
EXPOSE 8080

# Size the heap from the container's memory limit (not the host's), and exit on OOM so the orchestrator
# restarts a clean JVM instead of keeping a half-broken one alive.
ENV JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=75 -XX:InitialRAMPercentage=25 -XX:+ExitOnOutOfMemoryError"

# curl ships with the Temurin image. start-period covers Flyway migrations and Spring startup.
HEALTHCHECK --interval=15s --timeout=3s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/api/v1/health >/dev/null || exit 1

# OCI labels last: build args change on every commit, and an ARG declared earlier would become part of
# the cache key of every RUN after it.
ARG VERSION=dev
ARG REVISION=unknown
ARG CREATED=unknown
ARG SOURCE=https://github.com/SandeepKonduruRaju/ai-incident-platform
LABEL org.opencontainers.image.title="incident-service" \
      org.opencontainers.image.description="Incident API: JWT/RBAC, tenant isolation, transactional outbox to Kafka" \
      org.opencontainers.image.source="${SOURCE}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}" \
      org.opencontainers.image.version="${VERSION}"

# Exec form: java is PID 1 and receives SIGTERM for a graceful shutdown.
ENTRYPOINT ["java", "-jar", "application.jar"]
