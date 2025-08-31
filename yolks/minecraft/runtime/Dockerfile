ARG JAVA_VERSION=21
ARG MCDR_VERSION=latest

FROM mcdreforged/mcdreforged-zulu:${MCDR_VERSION}-slim-jdk${JAVA_VERSION}-extra

RUN set -eux; \
    apt-get update -y; \
    apt-get install -y --no-install-recommends curl ca-certificates openssl git tar sqlite3 fontconfig tzdata iproute2 gettext-base; \
    useradd -d /home/container -m container; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

COPY ./entrypoint.sh ./start_hook.py ./start_hook.yml /
RUN chmod +x /entrypoint.sh

USER container
ENV USER=container HOME=/home/container

WORKDIR /home/container

CMD ["/bin/bash", "/entrypoint.sh"]