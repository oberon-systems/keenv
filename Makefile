# Developer entry points for keenv. Run `make` for the target list.

VENV ?= .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
UV ?= uv

VERSION := $(shell sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)

.DEFAULT_GOAL := help

.PHONY: help init install test lint bump build publish clean require-uv require-token

help:  ## Show the current version and the available targets
	@echo "keenv $(VERSION)"
	@echo
	@echo "Targets:"
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  %-8s %s\n", $$1, $$2}' \
		$(MAKEFILE_LIST)

init:  ## Create the virtualenv, install everything and wire up the hooks
	python3 -m venv --prompt keenv $(VENV)
	$(PIP) install --upgrade pip
	$(MAKE) install
	$(VENV)/bin/pre-commit install

install:  ## Install the package in editable mode with dev dependencies
	$(PIP) install -r requirements.txt
	$(PIP) install --group dev

test:  ## Run the test suite
	$(VENV)/bin/pytest

lint:  ## Run the pre-commit hooks over every file
	$(VENV)/bin/pre-commit run --all-files

bump:  ## Bump the version, update the changelog and tag the release
	$(VENV)/bin/cz bump

build: require-uv clean  ## Build the wheel and the sdist into dist/
	$(UV) build

publish: require-token build  ## Upload the current version to PyPI (needs PYPI_TOKEN)
	UV_PUBLISH_TOKEN="$(PYPI_TOKEN)" $(UV) publish dist/keenv-$(VERSION)*

clean:  ## Remove the build artifacts from dist/
	rm -f dist/*.whl dist/*.tar.gz

require-uv:
	@command -v $(UV) >/dev/null 2>&1 || { \
		echo "$(UV) not found, install it first:" >&2; \
		echo "  https://docs.astral.sh/uv/getting-started/installation/" >&2; \
		exit 1; \
	}

require-token:
	@test -n "$(PYPI_TOKEN)" || { \
		echo "PYPI_TOKEN is not set, refusing to publish" >&2; \
		exit 1; \
	}
