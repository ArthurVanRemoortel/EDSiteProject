#!/bin/bash

# entrypoint.sh file of Dockerfile

# Section 1- Bash options
set -o errexit
set -o pipefail
set -o nounset

#echo "Waiting for postgres..."
#
#while ! nc -z db 5432; do
#  sleep 0.1
#done
#
#echo "PostgreSQL started"

cd /code

poetry --version
poetry install
#python manage.py collectstatic --noinput
# python manage.py makemigrations
python manage.py migrate
#gunicorn HSite.wsgi:application -c ./config/gunicorn/dev.py
python manage.py runserver 0.0.0.0:8070 --insecure --noreload

exec "$@"
