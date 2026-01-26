#!/usr/bin/env bash
set -e

# Start ollama serve in background
ollama serve &

# Đợi Ollama khởi động
sleep 10

# Pull model nếu chưa có
ollama pull qwen3-embedding || true

# Giữ container sống
tail -f /dev/null