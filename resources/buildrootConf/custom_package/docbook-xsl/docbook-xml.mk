################################################################################
#
# docbook-xml (host only), the DocBook XML 4.2 DTD that docbook-xsl pairs with
#
################################################################################

# DocBook XML 4.2 is frozen, so the version is not configurable. kmscon's man
# pages declare "-//OASIS//DTD DocBook XML V4.2//EN" and tools such as
# xsltproc --nonet try to load that DTD; without it every run prints
# "failed to load external entity" warnings.
DOCBOOK_XML_VERSION = 4.2
DOCBOOK_XML_SOURCE = docbook-xml-$(DOCBOOK_XML_VERSION).zip
DOCBOOK_XML_SITE = https://www.oasis-open.org/docbook/xml/$(DOCBOOK_XML_VERSION)
# No separate licence file: the permission notice is the header of the DTD.
DOCBOOK_XML_LICENSE = DocBook-XML
DOCBOOK_XML_LICENSE_FILES = docbookx.dtd

HOST_DOCBOOK_XML_DTD_DIR = $(HOST_DIR)/share/xml/docbook/xml-dtd-$(DOCBOOK_XML_VERSION)
# The archive ships its own XML catalog (public ids to relative files).
# docbook-xsl-catalog.xml chains to it, so users of that catalog get both.
HOST_DOCBOOK_XML_CATALOG = $(HOST_DOCBOOK_XML_DTD_DIR)/catalog.xml

# A zip, and with no top-level directory, so Buildroot's tar based default
# extraction does not apply: unpack straight into the build directory.
define HOST_DOCBOOK_XML_EXTRACT_CMDS
	$(UNZIP) -d $(@D) $(HOST_DOCBOOK_XML_DL_DIR)/$(HOST_DOCBOOK_XML_SOURCE)
endef

# Nothing to build: the DTD is used as it is.
define HOST_DOCBOOK_XML_INSTALL_CMDS
	$(INSTALL) -d -m 0755 $(HOST_DOCBOOK_XML_DTD_DIR)
	cp -a $(@D)/* $(HOST_DOCBOOK_XML_DTD_DIR)/
endef

# This file lives in the docbook-xsl directory, and Buildroot names a package
# after the directory of its .mk file, so it is declared by name here rather
# than with $(eval $(host-generic-package)). Enable symbol:
# BR2_PACKAGE_HOST_DOCBOOK_XML, hash file: docbook-xml.hash.
$(eval $(call inner-generic-package,host-docbook-xml,HOST_DOCBOOK_XML,DOCBOOK_XML,host))
