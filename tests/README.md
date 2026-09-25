# pg_cluster tests

The suite checks Ansible roles, renders templates using Ansible, and deploys a
three-node PostgreSQL cluster in Docker Compose.

## Local checks

```bash
pip install -r tests/requirements.txt 'ansible==9.6.1' 'ansible-core==2.16.19'
pip check
make lint test
```

The pinned `ansible` distribution includes the required collections. Install the
metapackage and core in the same pip invocation when choosing another matrix entry.

`make test` validates YAML in roles, inventory, tests and workflows, checks nested
handler references (including `listen`), renders templates with Ansible's actual
filters and undefined-variable handling, syntax-checks production and integration
playbooks, and runs regression tests for the harness. Any failed check returns a
nonzero exit status. Lint retains the project's configured style warnings.

## Docker integration

Docker Compose with `up --wait` support and privileged systemd containers is
required. The images use Ubuntu 22.04 for target nodes and a Python controller.

```bash
make test-docker   # Build, wait for SSH setup, verify versions, deploy and check
make down          # Remove this Compose project's containers and volumes
```

To keep a running test cluster separate from another one, select a unique project
and an unused /24 network prefix. Use the same environment for all commands:

```bash
export COMPOSE_PROJECT_NAME=pg-cluster-review
export TEST_SUBNET_PREFIX=10.21.0
make test-docker
make down
```

The default prefix is `10.20.0`; the controller uses `.10`, nodes `.11`–`.13`, and
VIP `.100`. Containers have project-scoped names. `make test-docker` keeps the
cluster for inspection; `make down` deletes its data.

All in-container targets explicitly select the controller Makefile:

```bash
docker compose -f tests/docker/docker-compose.yml exec -T ansible-controller \
  make -f /opt/Makefile.controller check-cluster
```

Health checks verify etcd endpoints, Patroni API availability, exact inventory
membership and one leader, and PostgreSQL recovery state on each node. SQL queries
exercise HAProxy's direct and pooled read/write ports, each PgBouncer instance,
and the VIP. A uniquely named probe table is written through the VIP, read back on
every PostgreSQL node with bounded retries, and dropped in an `always` block.

## Version matrix

`tests/version-matrix.yml` is the single source for local and CI combinations.
The default Ansible 9.6.1 entry pins core 2.16.19 — not its lowest compatible release
(2.16.7), but the lowest patch that satisfies the `ansible-lint==26.1.0` pin in
`tests/requirements.txt` (see the comment there).

Two entries are explicitly skipped: `py3.8-ansible7-patroni1.6` (Ansible 7 and core 2.14
require controller Python 3.9+) and `py3.9-ansible8-patroni2` (ansible-core 2.15.11,
which can't install `tests/requirements.txt` at all — `ansible-lint==26.1.0` needs both
ansible-core>=2.16.14, above what `ansible==8.7.0` allows, and Python>=3.10, above what
that entry's controller runs). See each entry's `reason` field in the matrix file.

```bash
make test-matrix
python3 tests/run_version_matrix.py --entry py3.11
python3 tests/run_version_matrix.py --entry py3.11 --keep
make test-matrix-static
python3 tests/run_version_matrix.py --list-json
```

Both matrix modes require Docker. `--static-only` skips deployment and health
checks, but still builds the requested images and verifies their installed
versions. Each full entry builds the controller and all target images with exact
Python/Ansible/core/Patroni settings, starts a fresh cluster, runs mandatory tests,
and removes containers and volumes. `--keep` requires selecting a single entry.
The runner removes this project's previous containers and volumes before each
entry: select a separate project when preserving another cluster.

## CI and coverage limits

GitHub Actions runs mandatory lint/local checks, one default Docker integration
combination, and local checks on every active Python/Ansible combination. CI's
static matrix does **not** test different Patroni runtimes; use the full Docker
matrix for that. CI saves Compose, Ansible and systemd logs and always tears down
the integration cluster.

The Docker image substitutes upstream packages for Tantor packages and supplies
fake package records, Tantor paths and systemd units. `pg_configurator` and
`modprobe` are stubs, and Patroni watchdog is disabled. These tests cover playbook
configuration and basic cluster operation, not Tantor package installation,
kernel watchdog behaviour, tuning correctness, failover or backup restoration.
A second deployment/idempotence check and destructive failover scenarios remain
separate future coverage.
