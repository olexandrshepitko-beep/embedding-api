FROM python:3.12-slim

# Установка зависимостей для сборки TDLib
RUN apt-get update && apt-get install -y \
    git cmake g++ make libssl-dev zlib1g-dev gperf \
    && rm -rf /var/lib/apt/lists/*

# Клонирование и сборка TDLib
WORKDIR /build
RUN git clone https://github.com/tdlib/td.git --depth 1 && \
    cd td && mkdir build && cd build && \
    cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local .. && \
    cmake --build . --target tdjson -j$(nproc) && \
    make install && \
    cd / && rm -rf /build

# Установка Python TDLib биндинга
WORKDIR /app
RUN pip install --no-cache-dir pytdlib pillow

COPY tdlib_auth.py /app/

EXPOSE 8080

CMD ["python3", "/app/tdlib_auth.py"]
