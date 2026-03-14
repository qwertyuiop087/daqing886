#!/bin/bash

echo "Starting bot..."

python bot.py &

echo "Starting web server..."

gunicorn server:app --bind 0.0.0.0:$PORT --workers 1
