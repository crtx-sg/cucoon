# Lightweight Meltano image. Plugins are installed from meltano.yml at build
# time so the nightly `docker compose run` starts fast.
FROM meltano/meltano:latest

WORKDIR /project
COPY meltano.yml /project/meltano.yml

# Pre-install the taps/targets declared in meltano.yml into the project venv.
RUN meltano install || true   # tolerate first-build network hiccups; re-run installs

# Default entrypoint is `meltano`; the compose `command`/cron supplies the job.
