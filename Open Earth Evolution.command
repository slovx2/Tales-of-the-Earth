#!/bin/zsh

set -euo pipefail

UNITY_EDITOR="/Applications/Unity/Hub/Editor/2022.3.62f3c1/Unity.app/Contents/MacOS/Unity"
PROJECT_PATH="$(cd "$(dirname "$0")" && pwd)"

if [[ ! -x "$UNITY_EDITOR" ]]; then
  osascript -e 'display alert "找不到 Unity 编辑器" message "请确认 Unity 2022.3.62f3c1 已安装。"'
  exit 1
fi

if pgrep -f "$UNITY_EDITOR.*-projectPath $PROJECT_PATH" >/dev/null; then
  osascript -e 'tell application "Unity" to activate'
  exit 0
fi

exec "$UNITY_EDITOR" -projectPath "$PROJECT_PATH"
