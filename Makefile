SHELL := /bin/bash
.DEFAULT_GOAL := all

SEVEN_Z := $(shell command -v 7zz 2>/dev/null || command -v 7z 2>/dev/null || command -v 7za 2>/dev/null)
ARCHIVE := dist/123pan-open-source.7z
PACKAGE_INPUTS := \
	LICENSE \
	Makefile \
	README.md \
	pyproject.toml \
	script/build.sh \
	src \
	uv.lock
PACKAGE_EXCLUDES := \
	-xr!__pycache__ \
	-xr!*.pyc

.PHONY: all
all: $(ARCHIVE)

$(ARCHIVE): $(PACKAGE_INPUTS) FORCE
	@if [[ -z "$(SEVEN_Z)" ]]; then \
		echo "7z command not found (tried: 7zz, 7z, 7za)" >&2; \
		exit 1; \
	fi
	mkdir -p dist
	rm -f "$(ARCHIVE)"
	"$(SEVEN_Z)" a -t7z "$(ARCHIVE)" $(PACKAGE_INPUTS) $(PACKAGE_EXCLUDES)

FORCE:
