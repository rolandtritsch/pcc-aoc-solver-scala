FROM node:24-trixie-slim@sha256:af02d57b57719b9657a45199a79264a9437940cd55b3c7b3fc99615654f124a0

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl git gh \
       openssh-server python3 ripgrep tini procps netcat-openbsd \
    && rm -rf /var/lib/apt/lists/* \
    && usermod -l paperclip -d /home/paperclip node \
    && groupmod -n paperclip node \
    && usermod -p '*' paperclip \
    && mkdir -p /home/paperclip /run/sshd /etc/ssh/authorized_keys \
    && chown paperclip:paperclip /home/paperclip \
    && rm -f /etc/ssh/ssh_host_*

COPY runtime/toolchain.json runtime/install-toolchain.py /opt/aoc-runtime/
RUN python3 /opt/aoc-runtime/install-toolchain.py
COPY runtime/launch.py /opt/aoc-runtime/launch.py
COPY runtime/entrypoint.sh /usr/local/bin/aoc-runtime-entrypoint
COPY runtime/agent.sh /usr/local/bin/aoc-agent
COPY runtime/sshd_config /etc/ssh/sshd_config
RUN chmod 755 /usr/local/bin/aoc-runtime-entrypoint /usr/local/bin/aoc-agent \
    && ln -s aoc-agent /usr/local/bin/aoc-opencode \
    && ln -s aoc-agent /usr/local/bin/aoc-cto

ENV JAVA_HOME=/opt/java \
    PATH=/opt/java/bin:/opt/sbt/bin:/usr/local/bin:/usr/bin:/bin \
    AOC_OPENCODE_BINARY=/usr/local/bin/opencode
RUN java -version && opencode --version && git --version && gh --version \
    && test -x /opt/sbt/bin/sbt

EXPOSE 22
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD nc -z 127.0.0.1 22 || exit 1
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/aoc-runtime-entrypoint"]
