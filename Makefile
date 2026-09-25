# Makefile — pg_cluster test orchestration
#
# Usage:
#   make test           — run static + template tests locally (no Docker)
#   make test-docker    — run full integration tests in Docker Compose
#   make test-matrix    — run version matrix tests (multiple Python/Ansible/Patroni)
#   make test-policy    — run libpq-dev package-policy checks on Astra/RedOS/ALT images
#   make up             — start the Docker test cluster
#   make down           — stop and remove the Docker test cluster
#   make lint           — run yamllint + ansible-lint
#   make syntax         — ansible syntax check
#   make templates      — render and validate Jinja2 templates
#   make clean          — remove generated artifacts

PYTHON      := python3
COMPOSE      := docker compose
COMPOSE_FILE := tests/docker/docker-compose.yml
ANSIBLE      := ansible-playbook
INVENTORY    := tests/docker/inventory/test_inventory
PLAYBOOK     := pg-cluster.yaml
EXTRA_VARS   := tests/docker/group_vars/all.yml

# Astra Linux 1.7 integration run (ALSE 1.7.3 nodes, target Python 3.7,
# controller ansible 10 / ansible-core 2.17, production tantordb path).
COMPOSE_ASTRA      := docker compose -f tests/docker/docker-compose.astra.yml
ANSIBLE_ASTRA_VARS := -i $(INVENTORY) -e @$(EXTRA_VARS) -e @tests/docker/astra-extra-vars.yml

# Default: run local static + template tests only
.PHONY: test test-docker test-matrix test-matrix-static test-policy test-astra astra-up test-astra-deploy astra-down up down lint syntax templates static clean help

## help: Show available targets
help:
	@echo "pg_cluster test targets:"
	@echo "  make test         — Run static + template tests locally (no Docker needed)"
	@echo "  make test-docker  — Run full integration tests in Docker Compose"
	@echo "  make test-matrix  — Run version matrix tests (Python/Ansible/Patroni combinations)"
	@echo "  make test-policy  — Run libpq-dev package-policy checks (Astra/RedOS/ALT images)"
	@echo "  make test-astra   — Full integration run on Astra Linux 1.7 nodes (Docker)"
	@echo "  make up           — Start the Docker test cluster"
	@echo "  make down         — Stop and remove the Docker test cluster"
	@echo "  make lint         — Run yamllint + ansible-lint"
	@echo "  make syntax       — Ansible syntax check"
	@echo "  make templates    — Render and validate Jinja2 templates"
	@echo "  make static       — Run static validation tests"
	@echo "  make clean        — Remove generated artifacts (pki, logs)"

## test: Run local static + template tests (no Docker required)
test: static templates syntax regression
	@echo "============================================"
	@echo "LOCAL TESTS PASSED"
	@echo "============================================"

## static: Run static validation (YAML, structure, handlers, playbook)
static:
	@echo "=== Static Validation Tests ==="
	$(PYTHON) tests/static/test_static.py

## templates: Render and validate Jinja2 templates
templates:
	@echo "=== Template Rendering Tests ==="
	$(PYTHON) tests/templates/test_templates.py

## lint: Run yamllint and ansible-lint
lint:
	@echo "=== YAML Lint ==="
	yamllint -c tests/.yamllint pg-cluster.yaml inventory/group_vars/ roles/ tests/ .github/workflows/
	@echo "=== Ansible Lint ==="
	ansible-lint -c tests/.ansible-lint pg-cluster.yaml roles/

## syntax: Ansible syntax check
syntax:
	@echo "=== Ansible Syntax Check ==="
	$(ANSIBLE) -i $(INVENTORY) -e @$(EXTRA_VARS) --syntax-check $(PLAYBOOK) tests/integration/prepare.yml tests/integration/check_cluster.yml

## up: Start Docker test cluster
up:
	$(COMPOSE) -f $(COMPOSE_FILE) up -d --build --wait --wait-timeout 900
	@echo "Cluster is ready. Run 'make test-docker' to run tests."

## down: Stop and remove Docker test cluster
down:
	$(COMPOSE) -f $(COMPOSE_FILE) down -v

## test-docker: Run full integration tests in Docker
test-docker: up
	$(COMPOSE) -f $(COMPOSE_FILE) exec -T ansible-controller make -f /opt/Makefile.controller test

## test-matrix: Run version matrix tests
test-matrix:
	$(PYTHON) tests/run_version_matrix.py

## test-policy: Run libpq-dev policy checks on real OS images (Docker, needs registry access)
test-policy:
	$(PYTHON) tests/docker/test_package_policy.py

## astra-up: Build and start the Astra test cluster
astra-up:
	$(COMPOSE_ASTRA) up -d --build --wait --wait-timeout 900

## test-astra-deploy: Deploy and verify on a running Astra test cluster
test-astra-deploy:
	$(COMPOSE_ASTRA) exec -T ansible-controller bash -lc "cd /opt/pg_cluster && ansible-playbook $(ANSIBLE_ASTRA_VARS) tests/integration/prepare.yml"
	$(COMPOSE_ASTRA) exec -T ansible-controller bash -lc "cd /opt/pg_cluster && ansible-playbook $(ANSIBLE_ASTRA_VARS) $(PLAYBOOK)"
	$(COMPOSE_ASTRA) exec -T ansible-controller bash -lc "cd /opt/pg_cluster && ansible-playbook $(ANSIBLE_ASTRA_VARS) tests/integration/check_cluster.yml"

## test-astra: Full integration run on Astra Linux SE 1.7 nodes (Docker, needs registry+nexus access)
test-astra: astra-up test-astra-deploy
	@echo "============================================"
	@echo "ASTRA INTEGRATION RUN PASSED"
	@echo "============================================"

## astra-down: Stop and remove the Astra test cluster
astra-down:
	$(COMPOSE_ASTRA) down -v

## test-matrix-static: Run only static tests for all matrix entries
test-matrix-static:
	$(PYTHON) tests/run_version_matrix.py --static-only

## clean: Remove generated artifacts
clean:
	rm -rf pki-dir/*
	rm -f ansible.log
	@echo "Cleaned generated artifacts"

## regression: Check the test harness itself
.PHONY: regression
regression:
	$(PYTHON) -m unittest discover -s tests/regression -v
