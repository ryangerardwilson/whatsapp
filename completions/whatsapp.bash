#!/usr/bin/env bash

_whatsapp_labels() {
  python3 - <<'PY'
import json
import os

def config_path():
    base = os.getenv("XDG_CONFIG_HOME")
    if not base:
        base = os.path.expanduser("~/.config")
    base = os.path.expanduser(base)
    return os.path.join(base, "whatsapp", "config.json")

path = config_path()
try:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle) or {}
except Exception:
    data = {}

labels = data.get("contact_labels") or {}
if isinstance(labels, dict):
    for key in labels.keys():
        if isinstance(key, str) and key.strip():
            print(key.strip())
PY
}

_whatsapp_complete() {
  local cur prev options
  COMPREPLY=()
  cur="${COMP_WORDS[COMP_CWORD]}"
  prev="${COMP_WORDS[COMP_CWORD-1]}"

  options="-c --clear -v --version -u --upgrade -h --help -ac --add-contact --profile --timeout"

  if [[ $cur == -* ]]; then
    COMPREPLY=( $(compgen -W "$options" -- "$cur") )
    return 0
  fi

  if [[ $prev == "--profile" ]]; then
    COMPREPLY=( $(compgen -f -- "$cur") )
    return 0
  fi

  if [[ $prev == "-ac" || $prev == "--add-contact" ]]; then
    return 0
  fi

  if [[ $prev == "--timeout" ]]; then
    return 0
  fi

  local cmd_offset=1

  if [[ ${COMP_CWORD} -eq $cmd_offset ]]; then
    COMPREPLY=( $(compgen -W "$(_whatsapp_labels)" -- "$cur") )
    return 0
  fi

  if [[ ${COMP_CWORD} -gt $cmd_offset ]]; then
    local idx=$cmd_offset
    local seen_positional=0
    while [[ $idx -lt ${COMP_CWORD} ]]; do
      case "${COMP_WORDS[$idx]}" in
        -c|--clear|-v|--version|-u|--upgrade|-h|--help)
          ;;
        --profile|--timeout)
          idx=$((idx + 1))
          ;;
        -ac|--add-contact)
          idx=$((idx + 2))
          ;;
        *)
          seen_positional=1
          ;;
      esac
      idx=$((idx + 1))
    done

    if [[ $seen_positional -eq 0 ]]; then
      COMPREPLY=( $(compgen -W "$(_whatsapp_labels)" -- "$cur") )
      return 0
    fi
  fi

  return 0
}

complete -o bashdefault -o default -F _whatsapp_complete whatsapp
