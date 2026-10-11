################################################################################
#
# python-freetype-py
#
################################################################################

PYTHON_FREETYPE_PY_VERSION = 2.5.1
PYTHON_FREETYPE_PY_SITE = $(call github,rougier,freetype-py,v$(PYTHON_FREETYPE_PY_VERSION))
PYTHON_FREETYPE_PY_SETUP_TYPE = pep517
PYTHON_FREETYPE_PY_LICENSE = BSD-3-Clause
PYTHON_FREETYPE_PY_LICENSE_FILES = LICENSE.txt doc/license.rst

# Pure Python: libfreetype is loaded with ctypes, not built here. The build backend
# needs setuptools, wheel and setuptools_scm. A GitHub tarball has no .git, so
# setuptools_scm is told the version instead of detecting it.
PYTHON_FREETYPE_PY_ENV = SETUPTOOLS_SCM_PRETEND_VERSION_FOR_FREETYPE_PY=$(PYTHON_FREETYPE_PY_VERSION)
HOST_PYTHON_FREETYPE_PY_ENV = $(PYTHON_FREETYPE_PY_ENV)

PYTHON_FREETYPE_PY_DEPENDENCIES = \
	freetype \
	host-python-setuptools \
	host-python-setuptools-scm \
	host-python-wheel

HOST_PYTHON_FREETYPE_PY_DEPENDENCIES = \
	host-freetype \
	host-python-setuptools \
	host-python-setuptools-scm \
	host-python-wheel

$(eval $(python-package))

$(eval $(host-python-package))
