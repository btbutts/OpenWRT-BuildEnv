#!/bin/bash
# Interactive non-login bash (for example `bash` from the root zsh login).
# Login bash already sourced these from /etc/profile.
if [ -r /etc/prompt.sh ]; then
    # shellcheck source=/etc/prompt.sh disable=1091
    . /etc/prompt.sh
fi
if [ -r /etc/shared-shell.sh ]; then
    # shellcheck source=/etc/shared-shell.sh disable=1091
    . /etc/shared-shell.sh
fi
