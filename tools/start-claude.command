#!/bin/zsh
# Mở một phiên Claude Code trong repo Motio với lời nhắc khởi động.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
cd "$(dirname "$0")/.."
exec claude --permission-mode acceptEdits "$(cat docs/KICKOFF.md)"
