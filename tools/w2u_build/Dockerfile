# Entorno para compilar White2Upgrade (necesita Linux): Ubuntu 24.04 trae arm-none-eabi-gcc 13.2, la versión que pide
# el proyecto. ndstool se compila desde su repositorio (devkitPro).
FROM ubuntu:24.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential git make python3 python3-yaml libpng-dev pkg-config ca-certificates \
        gcc-arm-none-eabi libnewlib-arm-none-eabi libstdc++-arm-none-eabi-newlib \
        openjdk-17-jre-headless autoconf automake \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 https://github.com/devkitPro/ndstool /tmp/ndstool \
    && cd /tmp/ndstool && ./autogen.sh && ./configure && make && make install && rm -rf /tmp/ndstool
COPY build.sh /build.sh
COPY fix_arm9.py /fix_arm9.py
WORKDIR /work
CMD ["sh", "/build.sh"]
