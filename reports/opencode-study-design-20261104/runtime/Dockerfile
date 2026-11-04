# Local base image ID verified by the build harness: sha256:17ad59a0efd3a62ede046c70b74213d649940e46a8330ac595ead4d647732bd6
FROM cami-probes:py312-pytest842
USER root
RUN apt-get update && apt-get install -y --no-install-recommends git ripgrep \
    && dpkg-query -W > /opt/runtime-dpkg-lock.txt \
    && rm -rf /var/lib/apt/lists/*
COPY python-deps/ /opt/cami-deps/
ENV PYTHONPATH=/opt/cami-src:/opt/cami-deps
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
ENV XDG_DATA_HOME=/state/data
ENV XDG_CONFIG_HOME=/state/config
ENV XDG_CACHE_HOME=/state/cache
ENV XDG_STATE_HOME=/state/state
ENV OPENCODE_TEST_HOME=/state/home
ENV OPENCODE_CONFIG_PROJECT_DISABLE=1
ENV OPENCODE_DISABLE_CLAUDE_CODE=1
ENV OPENCODE_DISABLE_MODELS_FETCH=1
WORKDIR /workspace
USER 65534:65534
ENTRYPOINT ["/opt/opencode"]
