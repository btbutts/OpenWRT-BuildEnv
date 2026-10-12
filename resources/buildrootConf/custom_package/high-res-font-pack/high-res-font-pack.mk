################################################################################
#
# high-res-font-pack
#
################################################################################

# Four fixed-width fonts for kmscon's FreeType renderer. Nothing is built: each
# archive is a Buildroot extra download, unpacked into a staging directory of the
# package's build directory, and copied to /usr/share/fonts/<Name>/ without the
# faces that are not used. Meant as a stop-gap until one font is composed from
# these. After a URL or an exclude below is changed, run
# "make high-res-font-pack-dirclean" so that the package is extracted again.
#
# Which faces are kept: kmscon asks fontconfig for weight "normal" and for
# "bold" and never sets a slant, so only the upright Regular and Bold files are
# used; the other weights and every italic are left out. Of the Nerd Fonts only
# the "Mono" builds are installed: in those the icons (private use area) are
# drawn inside one cell, in the plain builds nearly all of them are wider than a
# cell and kmscon would give each two. The "Propo" builds are proportional.
# JetBrains Mono "NL" is the same font (same glyphs and metrics) with its
# ligatures removed, and kmscon does no shaping, so it is left out.
#
# The order the families are tried in is not set here, it is font-name in
# /etc/kmscon/kmscon.conf (a rootfs overlay file, which is applied after package
# installation and so cannot be changed from this file).

HIGH_RES_FONT_PACK_VERSION = 1.0

# No main archive: everything is in HIGH_RES_FONT_PACK_EXTRA_DOWNLOADS
HIGH_RES_FONT_PACK_SITE =
HIGH_RES_FONT_PACK_SOURCE =

HIGH_RES_FONT_PACK_SOURCECODEPRO_URL = https://github.com/adobe-fonts/source-code-pro/releases/download/2.042R-u%2F1.062R-i%2F1.026R-vf/TTF-source-code-pro-2.042R-u_1.062R-i.zip
HIGH_RES_FONT_PACK_INCONSOLATA_URL = https://github.com/ryanoasis/nerd-fonts/releases/download/v3.5.1/Inconsolata.tar.xz
HIGH_RES_FONT_PACK_FIRAMONO_URL = https://github.com/ryanoasis/nerd-fonts/releases/download/v3.1.1/FiraMono.tar.xz
# The same file as download.jetbrains.com/fonts/JetBrainsMono-2.304.zip (identical
# SHA-256). That host redirects to a signed, expiring CDN address and its
# download-cdn name answers 404, so the release of the project on GitHub is used.
HIGH_RES_FONT_PACK_JETBRAINS_URL = https://github.com/JetBrains/JetBrainsMono/releases/download/v2.304/JetBrainsMono-2.304.zip

HIGH_RES_FONT_PACK_EXTRA_DOWNLOADS = \
	$(HIGH_RES_FONT_PACK_SOURCECODEPRO_URL) \
	$(HIGH_RES_FONT_PACK_INCONSOLATA_URL) \
	$(HIGH_RES_FONT_PACK_FIRAMONO_URL) \
	$(HIGH_RES_FONT_PACK_JETBRAINS_URL)

# Only Inconsolata, FiraMono and JetBrains ship a licence file, in their archive
# root. The Source Code Pro zip holds nothing but the TTF directory.
HIGH_RES_FONT_PACK_LICENSE = OFL-1.1
HIGH_RES_FONT_PACK_LICENSE_FILES = \
	staging/Inconsolata/OFL.txt \
	staging/FiraMono/LICENSE \
	staging/JetBrains/OFL.txt

HIGH_RES_FONT_PACK_STAGING = $(@D)/staging
HIGH_RES_FONT_PACK_FONTS_DIR = $(TARGET_DIR)/usr/share/fonts

# $(1): directory of the staging area, $(2): archive URL
define HIGH_RES_FONT_PACK_UNZIP
	mkdir -p $(HIGH_RES_FONT_PACK_STAGING)/$(1)
	$(UNZIP) -d $(HIGH_RES_FONT_PACK_STAGING)/$(1) \
		$(HIGH_RES_FONT_PACK_DL_DIR)/$(notdir $(2))
endef

define HIGH_RES_FONT_PACK_UNTAR
	mkdir -p $(HIGH_RES_FONT_PACK_STAGING)/$(1)
	$(call suitable-extractor,$(notdir $(2))) \
		$(HIGH_RES_FONT_PACK_DL_DIR)/$(notdir $(2)) | \
		$(TAR) -C $(HIGH_RES_FONT_PACK_STAGING)/$(1) $(TAR_OPTIONS) -
endef

define HIGH_RES_FONT_PACK_EXTRACT_CMDS
	rm -rf $(HIGH_RES_FONT_PACK_STAGING)
	$(call HIGH_RES_FONT_PACK_UNZIP,SourceCodePro,$(HIGH_RES_FONT_PACK_SOURCECODEPRO_URL))
	$(call HIGH_RES_FONT_PACK_UNTAR,Inconsolata,$(HIGH_RES_FONT_PACK_INCONSOLATA_URL))
	$(call HIGH_RES_FONT_PACK_UNTAR,FiraMono,$(HIGH_RES_FONT_PACK_FIRAMONO_URL))
	$(call HIGH_RES_FONT_PACK_UNZIP,JetBrains,$(HIGH_RES_FONT_PACK_JETBRAINS_URL))
endef

# Left out of every family (see the top of the file)
#	--exclude='*Medium*' \
#	--exclude='*SemiBold*' \
#	--exclude='*Semibold*'

HIGH_RES_FONT_PACK_EXCLUDES = \
	--exclude='*Thin*' \
	--exclude='*ExtraLight*' \
	--exclude='*Light*' \
	--exclude='*ExtraBold*' \
	--exclude='*Black*' \
	--exclude='*Italic*' \
	--exclude='*It.ttf' \
	--exclude='*Propo*' \
	--exclude='*NerdFont-*' \
	--exclude='*NL-*'

# $(1): directory under /usr/share/fonts, which is also the staging directory
# $(2): directory inside the archive that holds the fonts ("." for its root). Its
#       contents are copied into /usr/share/fonts/$(1)/, not the directory itself:
#       the fonts of the TTF/ (Source Code Pro) and fonts/ttf/ (JetBrains) directories
#       end up directly under /usr/share/fonts/SourceCodePro and .../JetBrains.
# The licence and authors files are at the root of the archive, so they are
# copied from there when the fonts are deeper (JetBrains), to stay with them.
define HIGH_RES_FONT_PACK_INSTALL_FAMILY
	mkdir -p $(HIGH_RES_FONT_PACK_FONTS_DIR)/$(1)
	rsync -rt --chmod=D755,F644 $(HIGH_RES_FONT_PACK_EXCLUDES) \
		$(HIGH_RES_FONT_PACK_STAGING)/$(1)/$(2)/ $(HIGH_RES_FONT_PACK_FONTS_DIR)/$(1)/
	rsync -rt --chmod=D755,F644 --include='OFL.txt' --include='LICENSE' \
		--include='AUTHORS.txt' --exclude='*' \
		$(HIGH_RES_FONT_PACK_STAGING)/$(1)/ $(HIGH_RES_FONT_PACK_FONTS_DIR)/$(1)/
	test -n "$$(find $(HIGH_RES_FONT_PACK_FONTS_DIR)/$(1) -type f \( -name '*.ttf' -o -name '*.otf' \))" || \
		{ echo "high-res-font-pack: no font was installed for $(1); did its archive change?" >&2; exit 1; }
endef

define HIGH_RES_FONT_PACK_INSTALL_TARGET_CMDS
	$(call HIGH_RES_FONT_PACK_INSTALL_FAMILY,SourceCodePro,TTF)
	$(call HIGH_RES_FONT_PACK_INSTALL_FAMILY,Inconsolata,.)
	$(call HIGH_RES_FONT_PACK_INSTALL_FAMILY,FiraMono,.)
	$(call HIGH_RES_FONT_PACK_INSTALL_FAMILY,JetBrains,fonts/ttf)
endef

$(eval $(generic-package))
