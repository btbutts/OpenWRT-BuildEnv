# Interactive non-login bash (e.g. `bash` from zsh). Login bash uses /etc/profile.
# shellcheck disable=SC1091,SC2148
alias vi=vim
if [ -r /etc/prompt.sh ]; then
    # shellcheck source=/etc/prompt.sh
    . /etc/prompt.sh
fi
