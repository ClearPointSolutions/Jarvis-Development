FROM jarvis-v1-mvp-python:local
USER root
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server \
    && rm -rf /var/lib/apt/lists/* && mkdir -p /run/sshd /workspaces /invocations /home/jarvis/.ssh \
    && passwd -d jarvis && chown -R jarvis:jarvis /workspaces /invocations /home/jarvis/.ssh
COPY tests/fixtures/runtime-worker/runner.py /fixture/runner.py
COPY tests/fixtures/runtime-worker/wrapper.py /fixture/wrapper.py
COPY tests/fixtures/runtime-worker/sshd_config /etc/ssh/sshd_config
EXPOSE 2222
CMD ["/usr/sbin/sshd", "-D", "-e"]
