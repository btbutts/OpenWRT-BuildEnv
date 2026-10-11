# Builds the chosen subset of console-setup's fonts with its own Makefile.
# Not named *.mk: external.mk includes every */*.mk as a Buildroot package.
# Run in console-setup's Fonts/ directory:
#   make -f select.makefile CODESETS="Uni1 Uni2" FACE_PATTERNS="Terminus% VGA%" selected
# Font names are <Codeset>-<Face><size>, e.g. Uni2-TerminusBold20x10.
# FACE_PATTERNS match <Face><size> (one % allowed); SKIP_PATTERNS, optional,
# exclude <Face><size> matches.

include Makefile

codeset_of = $(word 1,$(subst -, ,$(1)))
face_of = $(word 2,$(subst -, ,$(1)))
wanted = $(and $(filter $(CODESETS),$(call codeset_of,$(1))), \
	$(filter $(FACE_PATTERNS),$(call face_of,$(1))), \
	$(if $(filter $(SKIP_PATTERNS),$(call face_of,$(1))),,y))

CHOSEN := $(foreach name,$(GOOD_FONT_NAMES),$(if $(call wanted,$(name)),$(name)))

.PHONY: selected
selected: $(addprefix $(fntdir)/, $(addsuffix .psf.gz, $(CHOSEN)))
