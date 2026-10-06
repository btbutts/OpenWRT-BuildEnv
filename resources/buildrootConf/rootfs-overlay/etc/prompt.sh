# Sourced by /etc/profile (login bash), /etc/zshrc, and /root/.bashrc.
# Do not execute. Do not export PS1: zsh %F/%n/%m is not valid in bash.
#
# 256-color index 33 is #0087ff (xterm cube). Classic 16-color SGR 33
# is yellow; never use that for this prompt. TERM=linux is 8/16-color,
# so fall back to cyan (36), the closest light blue on the VT.
# shellcheck disable=SC2148

_prompt_suffix='$'
if [ "${USER:-}" = "root" ] || [ "$(id -u 2>/dev/null)" = "0" ]; then
    _prompt_suffix='#'
fi

_prompt_colors=0
if [ -n "${TERM:-}" ] && [ "${TERM}" != "dumb" ]; then
    _prompt_colors=$(tput colors 2>/dev/null) || _prompt_colors=0
fi

if [ -n "${ZSH_VERSION:-}" ]; then
    if [ "${_prompt_colors}" -ge 256 ]; then
        PROMPT="%F{33}[%n@%m %1~]%f${_prompt_suffix} "
    elif [ "${_prompt_colors}" -ge 8 ]; then
        PROMPT="%F{cyan}[%n@%m %1~]%f${_prompt_suffix} "
    else
        # shellcheck disable=SC2034
        PROMPT="[%n@%m %1~]${_prompt_suffix} "
    fi
    unset PS1
elif [ -n "${BASH_VERSION:-}" ]; then
    if [ "${_prompt_colors}" -ge 256 ]; then
        PS1="\[\e[38;5;33m\][\u@\h \W]${_prompt_suffix}\[\e[0m\] "
    elif [ "${_prompt_colors}" -ge 8 ]; then
        PS1="\[\e[36m\][\u@\h \W]${_prompt_suffix}\[\e[0m\] "
    else
        PS1="[\u@\h \W]${_prompt_suffix} "
    fi
fi
unset _prompt_suffix _prompt_colors
