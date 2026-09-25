#!/usr/bin/env python3
"""
Version matrix test runner for pg_cluster.

Reads tests/version-matrix.yml, and for each active entry:
1. Builds controller and nodes with the specified Python/Ansible/Patroni versions
2. Starts the Docker Compose cluster
3. Runs the test suite inside the controller
4. Collects and reports results
5. Tears down the cluster

Usage:
    python3 tests/run_version_matrix.py                    # run all active entries
    python3 tests/run_version_matrix.py --entry py3.11     # run a single entry by name substring
    python3 tests/run_version_matrix.py --keep             # don't tear down after run
    python3 tests/run_version_matrix.py --static-only      # only run static/template tests
"""

import argparse
import os
import subprocess
import sys
import json
import yaml
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPO_ROOT / "tests" / "docker" / "docker-compose.yml"
MATRIX_FILE = REPO_ROOT / "tests" / "version-matrix.yml"

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


def log(msg, color=RESET):
    print(f"{color}{msg}{RESET}")


def run_cmd(cmd, cwd=None, env=None, check=True, timeout=600):
    """Run a command, streaming output to stdout."""
    log(f"  $ {' '.join(cmd)}", CYAN)
    result = subprocess.run(
        cmd,
        cwd=cwd or str(REPO_ROOT),
        env={**os.environ, **(env or {})},
        check=False,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd)
    return result


def load_matrix():
    with open(MATRIX_FILE) as f:
        data = yaml.safe_load(f)
    return data.get("matrix", [])


def entry_env(entry):
    return {
        "PYTHON_VERSION": entry["python"],
        "ANSIBLE_VERSION": entry["ansible"],
        "ANSIBLE_CORE_VERSION": entry["ansible_core"],
        "PATRONI_VERSION": entry["patroni"],
    }


def build_cluster(entry):
    """Build both controller and target images for this exact matrix entry."""
    run_cmd(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "build"],
        env=entry_env(entry), timeout=1800,
    )


def start_cluster(entry):
    run_cmd(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "--no-build",
         "--wait", "--wait-timeout", "900"],
        env=entry_env(entry), timeout=960,
    )


def run_tests(entry, static_only=False):
    """Run the test suite inside the controller container."""
    if static_only:
        targets = ["versions", "lint", "static", "syntax", "template-test"]
    else:
        targets = ["test"]

    results = {}
    for target in targets:
        log(f"  Running 'make {target}'...", YELLOW)
        try:
            run_cmd(
                ["docker", "compose", "-f", str(COMPOSE_FILE), "exec", "-T",
                 "ansible-controller", "make", "-f", "/opt/Makefile.controller", target],
                env=entry_env(entry),
                timeout=900,
            )
            results[target] = "PASS"
            log(f"  {GREEN}✓ {target} PASSED{RESET}", GREEN)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            results[target] = "FAIL"
            log(f"  {RED}✗ {target} FAILED{RESET}", RED)

    return results


def teardown(entry, keep=False):
    """Tear down the Docker Compose cluster."""
    if keep:
        log("  Skipping teardown (--keep)", YELLOW)
        return
    log("  Tearing down cluster...", YELLOW)
    run_cmd(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v"],
        env=entry_env(entry),
        timeout=60,
    )


def main():
    parser = argparse.ArgumentParser(description="Run pg_cluster version matrix tests")
    parser.add_argument("--entry", type=str, default=None,
                        help="Run only entries whose name contains this substring")
    parser.add_argument("--keep", action="store_true",
                        help="Don't tear down the cluster after running")
    parser.add_argument("--static-only", action="store_true",
                        help="Only run static and template tests (no integration)")
    parser.add_argument("--list-json", action="store_true", help="Print the active CI matrix without Docker")
    args = parser.parse_args()

    matrix = load_matrix()
    active = [e for e in matrix if e.get("status", "active") == "active"]

    if args.entry:
        active = [e for e in active if args.entry.lower() in e["name"].lower()]

    if not active:
        log("No active matrix entries found.", RED)
        sys.exit(1)

    if args.list_json:
        print(json.dumps({"include": active}))
        return
    if args.keep and len(active) != 1:
        parser.error("--keep requires selecting exactly one entry, to avoid reusing cluster data")

    log(f"\n{'='*70}", BOLD)
    log(f"pg_cluster Version Matrix Test Runner", BOLD)
    log(f"{'='*70}", BOLD)
    log(f"Entries to test: {len(active)}")
    for e in active:
        log(f"  - {e['name']}: Python={e['python']}, Ansible={e['ansible']}, Patroni={e.get('patroni', 'N/A')}")
    log("")

    all_results = {}
    for i, entry in enumerate(active, 1):
        name = entry["name"]
        log(f"\n{'─'*70}", BOLD)
        log(f"[{i}/{len(active)}] {name}", BOLD)
        log(f"  Python={entry['python']}  Ansible={entry['ansible']}  Patroni={entry.get('patroni', 'N/A')}")
        log(f"{'─'*70}", BOLD)

        try:
            teardown(entry)
            build_cluster(entry)
            start_cluster(entry)
            results = run_tests(entry, static_only=args.static_only)
            all_results[name] = results
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            log(f"  {RED}Error during test execution: {e}{RESET}", RED)
            all_results[name] = {"error": str(e)}
        finally:
            try:
                teardown(entry, keep=args.keep)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                all_results.setdefault(name, {})["cleanup"] = str(exc)

    # Summary
    log(f"\n{'='*70}", BOLD)
    log(f"SUMMARY", BOLD)
    log(f"{'='*70}", BOLD)
    total_pass = 0
    total_fail = 0
    for name, results in all_results.items():
        log(f"\n  {name}:", BOLD)
        for target, status in results.items():
            if status == "PASS":
                log(f"    {GREEN}✓{RESET} {target}")
                total_pass += 1
            else:
                log(f"    {RED}✗{RESET} {target}: {status}")
                total_fail += 1

    log(f"\n{'─'*70}")
    log(f"Total: {GREEN}{total_pass} passed{RESET}, {RED}{total_fail} failed{RESET}")
    log(f"{'='*70}")

    sys.exit(1 if total_fail > 0 else 0)


if __name__ == "__main__":
    main()
