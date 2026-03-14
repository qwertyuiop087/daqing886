#!/bin/bash
echo "Starting web server..."
gunicorn server:app --bind 0.0.0.0:$PORT --workers 1 &
echo "Starting bot..."
python bot.py
