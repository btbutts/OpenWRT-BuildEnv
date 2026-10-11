################################################################################
#
# docbook-xsl (host only)
#
################################################################################

# The release is frozen (DocBook XSL 1.x is no longer developed), so the
# version is not configurable.
DOCBOOK_XSL_VERSION = 1.79.2
# The "nons" release is the non-namespaced one, which is what DocBook 4
# sources (kmscon's man pages, for one) need. The plain docbook-xsl tarball is
# the namespaced release: given a DocBook 4 page it indents every roff macro,
# which makes the generated man page unreadable.
DOCBOOK_XSL_SOURCE = docbook-xsl-nons-$(DOCBOOK_XSL_VERSION).tar.gz
DOCBOOK_XSL_SITE = https://github.com/docbook/xslt10-stylesheets/releases/download/release%2F$(DOCBOOK_XSL_VERSION)
DOCBOOK_XSL_LICENSE = DocBook-Stylesheet
DOCBOOK_XSL_LICENSE_FILES = COPYING

# Where the stylesheets and their catalog are installed.
HOST_DOCBOOK_XSL_STYLESHEETS_DIR = $(HOST_DIR)/share/xml/docbook/xsl-stylesheets
# Point XML_CATALOG_FILES at this for xsltproc --nonet to resolve
# http://docbook.sourceforge.net/release/xsl/{current,1.79.2}/... The URL is
# only an identifier here, nothing is fetched from that host.
HOST_DOCBOOK_XSL_CATALOG = $(HOST_DOCBOOK_XSL_STYLESHEETS_DIR)/docbook-xsl-catalog.xml

# The stylesheets are always used together with the DocBook XML DTD that the
# man pages are written against (docbook-xml.mk), which the catalog chains to.
HOST_DOCBOOK_XSL_DEPENDENCIES = host-docbook-xml

# Nothing to build: the stylesheets are used as they are. The upstream
# catalog.xml only maps cdn.docbook.org, so docbook-xsl-catalog.xml adds the
# docbook.sourceforge.net names that DocBook-using build systems refer to, and
# chains to the upstream catalog.
define HOST_DOCBOOK_XSL_INSTALL_CMDS
	$(INSTALL) -d -m 0755 $(HOST_DOCBOOK_XSL_STYLESHEETS_DIR)
	cp -a $(@D)/* $(HOST_DOCBOOK_XSL_STYLESHEETS_DIR)/
	$(INSTALL) -m 0644 $(HOST_DOCBOOK_XSL_PKGDIR)/docbook-xsl-catalog.xml \
		$(HOST_DOCBOOK_XSL_CATALOG)
endef

$(eval $(host-generic-package))
