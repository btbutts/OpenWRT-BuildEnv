# Sourced by /etc/profile (login bash), /etc/zshrc (interactive zsh),
# and /root/.bashrc (non-login interactive bash). Do not execute.
# Functions are not inherited by child shells; do not put this in profile.d.
# shellcheck disable=SC2148

# ls -alh with the permission bits as a leading octal mode.
lsnum() {
    # shellcheck disable=SC2016
    local parse_perms='{k=0;for(i=0;i<=8;i++)k+=((substr($1,i+2,1)~/[rwx]/)*2^(8-i));if(k)printf("%0o ",k);print}'

    # Use current directory if no arguments are provided, otherwise use all arguments
    # shellcheck disable=SC2012
    ls -alh "${@:-.}" | awk "$parse_perms"
}
