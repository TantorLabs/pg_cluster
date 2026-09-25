#!/usr/bin/env python3
"""Fail if the installed runtime differs from the requested matrix entry."""
import argparse
import os
import platform
from importlib.metadata import version


def check(label, actual, expected):
    print(f"{label}: {actual} (expected {expected})", flush=True)
    if not expected or actual != expected:
        raise SystemExit(f"Unexpected {label} version")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--patroni', help='Check a target node instead of the controller')
    args = parser.parse_args()
    if args.patroni:
        check('patroni', version('patroni'), args.patroni)
    else:
        check('python', '.'.join(platform.python_version_tuple()[:2]), os.environ['PYTHON_VERSION'])
        check('ansible', version('ansible'), os.environ['ANSIBLE_VERSION'])
        check('ansible-core', version('ansible-core'), os.environ['ANSIBLE_CORE_VERSION'])


if __name__ == '__main__':
    main()
