#!/usr/bin/env python3
"""Package-policy integration test on real OS container images.

Verifies the libpq-dev installation policy (libpq-dev is installed only
when the OS provides no psycopg2 package) by running the actual
roles/prepare_nodes task files inside containers built from the target
distribution images:

    1. registry.astralinux.ru/library/alse:1.7.3   (Astra Linux, apt)
    2. registry.red-soft.ru/redos7c/ubi            (RED OS 7, dnf)
       NOTE: registry.red-soft.ru/ubi7/redos7c does not exist; the RedOS
       UBI 7 image lives under redos7c/ubi.
    3. registry.altlinux.org/p10/alt:latest        (ALT Linux p10, apt-rpm)

Per apt-family image the runner executes three phases (see
tests/integration/package_policy.yml): natural state, forced fallback
(psycopg2 made undetectable) and an idempotency re-run. RED OS runs the
natural phase twice (the role installs runtime libpq there unconditionally).

Requirements: docker CLI with access to the registries, ansible-playbook
on PATH with the community.docker collection and the `docker` Python SDK
installed (see tests/requirements.txt).

Usage:
    python3 tests/docker/test_package_policy.py [--image astra|redos|alt] [--keep]
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = REPO_ROOT / "tests" / "integration" / "package_policy.yml"

IMAGES = [
    {
        "alias": "astra",
        "image": "registry.astralinux.ru/library/alse:1.7.3",
        # Minimal image: no python3, hence no ansible target support yet.
        "bootstrap": "apt-get update -qq && apt-get install -y -qq python3 python3-apt",
        # Astra path of the role does not need the Tantor nexus repository.
        "add_nexus_repo": "false",
    },
    {
        "alias": "redos",
        "image": "registry.red-soft.ru/redos7c/ubi:latest",
        "bootstrap": None,
        "add_nexus_repo": "false",
    },
    {
        "alias": "alt",
        "image": "registry.altlinux.org/p10/alt:latest",
        # Minimal image: bootstrap python3 via apt-rpm for ansible modules.
        "bootstrap": "apt-get update && apt-get install -y python3",
        # The ALT branch of prepare_nodes is gated by add_nexus_repo.
        "add_nexus_repo": "true",
    },
]

PHASES = ["natural", "fallback", "idempotency"]
RECAP_RE = re.compile(
    r"^(?P<host>\S+)\s*:\s*ok=(?P<ok>\d+)\s+changed=(?P<changed>\d+)"
    r"\s+unreachable=(?P<unreachable>\d+)\s+failed=(?P<failed>\d+)",
    re.MULTILINE,
)


def run(cmd, **kwargs):
    """Run a command, returning CompletedProcess with nice failure output."""
    print(f"  $ {' '.join(str(c) for c in cmd)}", flush=True)
    return subprocess.run(
        [str(c) for c in cmd],
        capture_output=True,
        text=True,
        **kwargs,
    )


def docker(args, check=True):
    result = run(["docker", *args])
    if check and result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"docker {' '.join(str(a) for a in args)} failed")
    return result


def ensure_image(image):
    if docker(["inspect", image], check=False).returncode == 0:
        return
    print(f"  pulling {image} ...")
    docker(["pull", image])


def start_container(alias, image):
    name = f"pgcluster-policy-{alias}"
    docker(["rm", "-f", name], check=False)
    docker(["run", "-d", "--name", name, "--entrypoint", "/bin/sh", image, "-c", "sleep infinity"])
    return name


def bootstrap(container, bootstrap_cmd):
    if not bootstrap_cmd:
        return
    result = docker(["exec", container, "/bin/sh", "-c", bootstrap_cmd], check=False)
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"bootstrap failed on {container}")


def ansible_env(tmpdir):
    env = dict(os.environ)
    # Keep ansible scratch files out of a possibly read-only HOME.
    env["ANSIBLE_LOCAL_TMP"] = str(tmpdir)
    env["ANSIBLE_HOST_KEY_CHECKING"] = "False"
    # Local convenience: a workspace-local pure-python docker SDK install
    # (created with `pip install --target .ansible/pylibs docker`) so the
    # docker connection plugin works even without a system-wide SDK.
    pylibs = REPO_ROOT / ".ansible" / "pylibs"
    if pylibs.is_dir():
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in [str(pylibs), env.get("PYTHONPATH", "")] if p
        )
    return env


def write_inventory(tmpdir, alias, container):
    inventory = tmpdir / "inventory.ini"
    inventory.write_text(
        f"{alias} ansible_host={container} "
        "ansible_connection=community.docker.docker "
        "ansible_user=root ansible_python_interpreter=/usr/bin/python3\n"
    )
    return str(inventory)


def run_phase(name, container, image_cfg, tmpdir, phase):
    extra = [
        "-e", f"policy_add_nexus_repo={image_cfg['add_nexus_repo']}",
        "-e", f"policy_force_fallback={'true' if phase == 'fallback' else 'false'}",
        # Normalize (remove any dev package) only before the first natural
        # run; the fallback and idempotency phases must observe the state
        # left by the previous phase.
        "-e", f"policy_normalize={'true' if phase == 'natural' else 'false'}",
    ]
    result = run(
        [
            "ansible-playbook",
            "-i", write_inventory(tmpdir, name, container),
            *extra,
            str(PLAYBOOK),
        ],
        cwd=REPO_ROOT,
        env=ansible_env(tmpdir),
        timeout=1800,
    )
    recap = RECAP_RE.search(result.stdout)
    if result.returncode != 0 or not recap or int(recap.group("failed")) != 0:
        print(result.stdout[-4000:])
        print(result.stderr[-2000:], file=sys.stderr)
        raise RuntimeError(f"phase '{phase}' failed on {name}")
    print(f"  [{phase}] {recap.group(0).strip()}")
    return {key: int(recap.group(key)) for key in ("ok", "changed", "failed")}


def check_image(cfg, keep):
    alias, image = cfg["alias"], cfg["image"]
    print(f"=== {alias}: {image}")
    ensure_image(image)
    container = start_container(alias, image)
    tmpdir = Path(tempfile.mkdtemp(prefix="pgcluster-policy-"))
    try:
        bootstrap(container, cfg["bootstrap"])
        stats = {}
        for phase in PHASES:
            stats[phase] = run_phase(alias, container, cfg, tmpdir, phase)
        if stats["idempotency"]["changed"] != 0:
            raise RuntimeError(
                f"{alias}: expected an idempotent re-run, "
                f"got changed={stats['idempotency']['changed']}"
            )
        print(f"=== {alias}: PASS")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        if not keep:
            docker(["rm", "-f", container], check=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", choices=[cfg["alias"] for cfg in IMAGES],
                        help="run a single image instead of all of them")
    parser.add_argument("--keep", action="store_true",
                        help="keep containers after the run (for debugging)")
    args = parser.parse_args()

    if shutil.which("ansible-playbook") is None:
        sys.exit("ansible-playbook not found on PATH")
    if shutil.which("docker") is None:
        sys.exit("docker CLI not found on PATH")

    selected = [cfg for cfg in IMAGES if args.image in (None, cfg["alias"])]
    failures = []
    for cfg in selected:
        try:
            check_image(cfg, keep=args.keep)
        except Exception as exc:  # noqa: BLE001 — test runner reports and continues
            print(f"=== {cfg['alias']}: FAIL ({exc})", flush=True)
            failures.append(cfg["alias"])

    if failures:
        sys.exit(f"package-policy test FAILED for: {', '.join(failures)}")
    print("package-policy test PASSED for all images")


if __name__ == "__main__":
    main()
