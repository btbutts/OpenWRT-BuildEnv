# Sourced by /etc/profile (login bash) and /etc/zshrc (interactive zsh).
# Do not execute. Do not export PS1: zsh %F/%n/%m is not valid in bash.
#
# 256-color index 33 is #0087ff (xterm cube). Classic 16-color SGR 33
# is yellow; never use that for this prompt. TERM=linux is 8/16-color,
# so fall back to cyan (36), the closest light blue on the VT.
#
# In zsh, PS1 and PROMPT name the same parameter. Assign PS1 (ShellCheck
# treats it as used). Never unset PS1 after setting the prompt.
# shellcheck disable=SC2148

_prompt_suffix='$'
if [ "${USER:-}" = "root" ] || [ "$(id -u 2>/dev/null)" = "0" ]; then
    _prompt_suffix='#'
fi

# Integer only: empty, "-1", or "unknown" from tput must not reach `[ -ge ]`.
_prompt_colors=0
if [ -n "${TERM:-}" ] && [ "${TERM}" != "dumb" ]; then
    _tput_colors=$(tput colors 2>/dev/null) || _tput_colors=
    case "${_tput_colors}" in
        ''|*[!0-9]*) _prompt_colors=0 ;;
        *) _prompt_colors="${_tput_colors}" ;;
    esac
    unset _tput_colors
fi

if [ -n "${ZSH_VERSION:-}" ]; then
    if [ "${_prompt_colors}" -ge 256 ]; then
        PS1="%F{33}[%n@%m %1~]%f${_prompt_suffix} "
    elif [ "${_prompt_colors}" -ge 8 ]; then
        PS1="%F{cyan}[%n@%m %1~]%f${_prompt_suffix} "
    else
        PS1="[%n@%m %1~]${_prompt_suffix} "
    fi
    # Drop the export flag so a child bash does not inherit %F sequences.
    # zsh export(1) has no -n; typeset +x is the zsh (and bash) form.
    typeset +x PS1
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
