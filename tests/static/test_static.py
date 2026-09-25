#!/usr/bin/env python3
"""
Static validation tests for pg_cluster Ansible roles.

Checks:
1. All role task files are valid YAML
2. Role directory structure follows Ansible conventions
3. All handlers referenced in tasks exist in handler files
4. All Jinja2 templates can be parsed
5. Playbook structure is valid
"""

import sys
import yaml
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ROLES_DIR = REPO_ROOT / "roles"
GROUP_VARS_DIR = REPO_ROOT / "inventory" / "group_vars"

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

passed = 0
failed = 0
warnings = 0


def ok(msg):
    global passed
    passed += 1
    print(f"  {GREEN}✓{RESET} {msg}")


def fail(msg):
    global failed
    failed += 1
    print(f"  {RED}✗{RESET} {msg}")


def warn(msg):
    global warnings
    warnings += 1
    print(f"  {YELLOW}⚠{RESET} {msg}")


def load_yaml(path):
    try:
        with open(path) as f:
            return yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:
        fail(f"Cannot load {path}: {exc}")
        return None


def yaml_files_under(directory):
    return sorted(p for p in directory.rglob('*') if p.is_file() and p.suffix in ('.yml', '.yaml'))


def walk_tasks(tasks):
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        yield task
        for section in ('block', 'rescue', 'always'):
            yield from walk_tasks(task.get(section, []))


def test_role_structure():
    """Verify each role has the expected directory structure."""
    print("\n[Test] Role directory structure")
    for role_dir in sorted(ROLES_DIR.iterdir()):
        if not role_dir.is_dir():
            continue
        role_name = role_dir.name
        tasks_dir = role_dir / "tasks"
        if any((tasks_dir / name).is_file() for name in ("main.yml", "main.yaml")):
            ok(f"Role '{role_name}' has a main task file")
        else:
            fail(f"Role '{role_name}' missing tasks/main.yml")


def test_yaml_valid():
    """Verify all YAML files in roles are valid."""
    print("\n[Test] YAML syntax in roles")
    yaml_files = yaml_files_under(ROLES_DIR)
    if not yaml_files:
        fail("No role YAML files found")
    yaml_files.extend(yaml_files_under(GROUP_VARS_DIR))
    yaml_files.extend(yaml_files_under(REPO_ROOT / 'tests'))
    yaml_files.extend(yaml_files_under(REPO_ROOT / '.github' / 'workflows'))
    playbook = REPO_ROOT / "pg-cluster.yaml"
    if playbook.exists():
        yaml_files.append(playbook)

    for yml_file in sorted(yaml_files):
        rel = yml_file.relative_to(REPO_ROOT)
        failures_before = failed
        load_yaml(yml_file)
        if failed == failures_before:
            ok(f"Valid YAML: {rel}")


def test_handlers_exist():
    """Check that all notify handlers referenced in tasks are defined."""
    print("\n[Test] Handler references")
    for role_dir in sorted(ROLES_DIR.iterdir()):
        if not role_dir.is_dir():
            continue
        role_name = role_dir.name

        handler_names = set()
        handlers_dir = role_dir / "handlers"
        if handlers_dir.is_dir():
            for hf in yaml_files_under(handlers_dir):
                data = load_yaml(hf)
                if data and isinstance(data, list):
                    for item in walk_tasks(data):
                        if isinstance(item, dict) and "name" in item:
                            handler_names.add(item["name"])
                        topics = item.get('listen', [])
                        handler_names.update([topics] if isinstance(topics, str) else topics)

        notify_refs = set()
        tasks_dir = role_dir / "tasks"
        if tasks_dir.is_dir():
            for tf in yaml_files_under(tasks_dir):
                data = load_yaml(tf)
                if data and isinstance(data, list):
                    for item in walk_tasks(data):
                        if isinstance(item, dict) and "notify" in item:
                            notifies = item["notify"]
                            if isinstance(notifies, str):
                                notify_refs.add(notifies)
                            elif isinstance(notifies, list):
                                notify_refs.update(notifies)

        for ref in sorted(notify_refs):
            if ref in handler_names:
                ok(f"Role '{role_name}': handler '{ref}' found")
            else:
                fail(f"Role '{role_name}': handler '{ref}' NOT found in handlers/")


def test_templates_parse():
    """Check that all Jinja2 templates can be parsed."""
    print("\n[Test] Jinja2 template parsing")
    for role_dir in sorted(ROLES_DIR.iterdir()):
        if not role_dir.is_dir():
            continue
        role_name = role_dir.name
        templates_dir = role_dir / "templates"
        if not templates_dir.is_dir():
            continue

        for tmpl in sorted(templates_dir.iterdir()):
            if tmpl.suffix not in (".j2",):
                continue
            rel = tmpl.relative_to(REPO_ROOT)
            try:
                with open(tmpl) as f:
                    content = f.read()
                env = Environment(loader=FileSystemLoader(str(templates_dir)))
                env.parse(content)
                ok(f"Template parses: {rel}")
            except Exception as e:
                fail(f"Template parse error: {rel}: {e}")


def test_playbook_structure():
    """Verify the main playbook has valid plays with hosts and roles."""
    print("\n[Test] Playbook structure")
    playbook = REPO_ROOT / "pg-cluster.yaml"
    data = load_yaml(playbook)
    if not data or not isinstance(data, list):
        fail("pg-cluster.yaml is not a valid playbook list")
        return

    for i, play in enumerate(data):
        if not isinstance(play, dict):
            fail(f"Play #{i} is not a dict")
            continue
        play_name = play.get("name", f"play-{i}")

        if "hosts" not in play:
            fail(f"Play '{play_name}': missing 'hosts'")
        else:
            ok(f"Play '{play_name}': has hosts='{play['hosts']}'")

        if "roles" in play:
            for role in play["roles"]:
                if isinstance(role, dict):
                    role_name = role.get("role", "unknown")
                else:
                    role_name = role
                role_path = ROLES_DIR / role_name
                if role_path.is_dir():
                    ok(f"Play '{play_name}': role '{role_name}' exists")
                else:
                    fail(f"Play '{play_name}': role '{role_name}' NOT found in roles/")

        if "tags" in play:
            ok(f"Play '{play_name}': tagged '{play['tags']}'")


def main():
    print("=" * 60)
    print("pg_cluster — Static Validation Tests")
    print("=" * 60)

    test_role_structure()
    test_yaml_valid()
    test_handlers_exist()
    test_templates_parse()
    test_playbook_structure()

    print("\n" + "=" * 60)
    print(f"Results: {GREEN}{passed} passed{RESET}, {RED}{failed} failed{RESET}, {YELLOW}{warnings} warnings{RESET}")
    print("=" * 60)

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
