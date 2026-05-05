FROM alpine:3.20

RUN apk add --no-cache \
    python3 \
    python3-dev \
    py3-pip \
    gcc \
    musl-dev \
    make \
    linux-headers \
    libffi-dev \
    vim \
    gdb

WORKDIR /project
COPY . .

# _cdlml C extension is skipped silently (no dlmopen on musl).
# cdlml_server binary is compiled and used as fallback.
ENV CDLML_DEBUG=1
ENV CFLAGS="-g3 -O0 -fno-omit-frame-pointer -fno-optimize-sibling-calls"
ENV CXXFLAGS="-g3 -O0 -fno-omit-frame-pointer -fno-optimize-sibling-calls"
ENV LDFLAGS="-g"
RUN python3 -m pip install --break-system-packages -e .[dev] -v

RUN make -C tests clean && make -C tests

CMD ["python3", "-m", "pytest", "tests/"]
