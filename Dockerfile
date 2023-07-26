# syntax=docker/dockerfile:1
# https://stackoverflow.com/questions/53835198/integrating-python-poetry-with-docker
FROM python:3.10.5
EXPOSE 6379

ARG YOUR_ENV

ENV PIP_DISABLE_PIP_VERSION_CHECK=on
ENV YOUR_ENV=${YOUR_ENV} \
  PYTHONFAULTHANDLER=1 \
  PYTHONUNBUFFERED=1 \
  PYTHONHASHSEED=random \
  PIP_NO_CACHE_DIR=off \
  PIP_DISABLE_PIP_VERSION_CHECK=on \
  PIP_DEFAULT_TIMEOUT=100 \
  POETRY_VERSION=1.4.0

# System deps:
RUN pip install "poetry==$POETRY_VERSION"

# Copy only requirements to cache them in docker layer
WORKDIR /code
COPY poetry.lock pyproject.toml /code/

# Project initialization:
RUN poetry config virtualenvs.create false  \
    && poetry install --no-interaction --no-ansi

# Creating folders, and files for a project:
COPY . /code

ADD docker-entrypoint.sh /code/docker-entrypoint.sh
RUN chmod a+x /code/docker-entrypoint.sh
ENTRYPOINT ["/code/docker-entrypoint.sh"]

