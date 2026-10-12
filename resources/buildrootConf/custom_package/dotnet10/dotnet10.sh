#!/bin/bash
# .NET 10 SDK environment. Sourced by /etc/profile (bash and zsh).
export DOTNET_ROOT=/opt/dotnet10
case ":$PATH:" in
	*":$DOTNET_ROOT:"*) ;;
	*) PATH="$PATH:$DOTNET_ROOT" ;;
esac
export PATH

# Use the system ICU instead of invariant globalization (0 is the .NET
# default; set explicitly so a stray environment value cannot flip it).
export DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0
