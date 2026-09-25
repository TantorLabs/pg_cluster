#!/usr/bin/env python3
"""
Template rendering tests for pg_cluster.

Renders each role template with fixture variables and validates:
1. The rendered output is syntactically valid for the target format
2. No undefined variables remain in the output
3. Key configuration values are present in the rendered output
"""

import re
import sys
import yaml
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ROLES_DIR = REPO_ROOT / "roles"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"

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


def load_fixture(name):
    """Load a fixture YAML file."""
    path = FIXTURES_DIR / name
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_group_vars():
    """Load all group_vars and merge."""
    merged = {}
    gv_dir = REPO_ROOT / "inventory" / "group_vars"
    for yml_file in sorted(gv_dir.glob("*.yml")):
        with open(yml_file) as f:
            data = yaml.safe_load(f)
        if data and isinstance(data, dict):
            merged.update(data)
    # Also load test group_vars
    test_gv = REPO_ROOT / "tests" / "docker" / "group_vars"
    if test_gv.is_dir():
        for yml_file in sorted(test_gv.glob("*.yml")):
            with open(yml_file) as f:
                data = yaml.safe_load(f)
            if data and isinstance(data, dict):
                merged.update(data)
    return merged


def make_hostvars(nodes):
    """Build a hostvars-like dict for template rendering."""
    hostvars = {}
    for i, node in enumerate(nodes, 1):
        hostvars[node] = {
            "ansible_facts": {
                "default_ipv4": {"address": f"10.20.0.{10+i}", "interface": "eth0"},
                "fqdn": node,
                "os_family": "Debian",
            },
            "ansible_host": f"10.20.0.{10+i}",
            "inventory_hostname": node,
            "unified_hostname": node,
        }
    return hostvars


try:
    # ansible-core >=2.19 (data tagging): only strings tagged as trusted are
    # rendered as Jinja templates -- everything else is silently passed through
    # unrendered. A plain str read from disk (or from yaml.safe_load, as our
    # fixtures and group_vars are) is untrusted, so it must be tagged explicitly.
    # Older ansible-core has no such restriction (and no such helper).
    from ansible.template import trust_as_template
except ImportError:
    def trust_as_template(value):
        return value


def _trust_recursive(value):
    """Tag every string in a nested structure as trusted for templating.

    Needed for variable VALUES too, not just the top-level template string:
    group_vars/fixtures routinely define one variable in terms of another
    (e.g. haproxy_patroni_auth: "{{ patroni_restapi_username }}:...") and
    ansible-core >=2.19 won't re-template an untrusted variable value either.
    """
    if isinstance(value, str):
        return trust_as_template(value)
    if isinstance(value, dict):
        return {k: _trust_recursive(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_trust_recursive(v) for v in value]
    return value


def render_template(template_path, context):
    """Use Ansible's own recursive variable resolution, filters and Jinja header."""
    from ansible.parsing.dataloader import DataLoader
    from ansible.template import Templar

    variables = dict(context)
    variables.setdefault("playbook_dir", str(REPO_ROOT))
    variables.setdefault("ansible_inventory_sources", [str(REPO_ROOT / "tests/docker/inventory/test_inventory")])
    variables = _trust_recursive(variables)
    variables["vars"] = dict(variables)
    loader = DataLoader()
    loader.set_basedir(str(template_path.parent))
    templar = Templar(loader=loader, variables=variables)

    # convert_data is deprecated (removed in ansible-core 2.23): jinja2 native
    # mode is now unconditional and the flag no longer does anything there.
    # `evaluate_expression` only exists on the >=2.19 Templar, so use it as the
    # version probe rather than a hasattr version-parsing dance.
    kwargs = {} if hasattr(templar, "evaluate_expression") else {"convert_data": False}

    return templar.template(
        trust_as_template(template_path.read_text()), fail_on_undefined=True,
        preserve_trailing_newlines=True, **kwargs,
    )


def test_patroni_yml_template():
    """Test rendering patroni.yml.j2 with fixture vars."""
    print("\n[Test] patroni.yml.j2 rendering")
    tmpl = ROLES_DIR / "patroni" / "templates" / "patroni.yml.j2"
    if not tmpl.exists():
        fail("patroni.yml.j2 not found")
        return

    group_vars = load_group_vars()
    fixture = load_fixture("patroni_vars.yml")
    context = {**group_vars, **fixture}

    nodes = ["pg-node1", "pg-node2", "pg-node3"]
    context["groups"] = {"all": nodes, "inv_pg": nodes, "inv_etcd": nodes, "inv_cluster": nodes, "inv_keepalived": nodes}
    context["hostvars"] = make_hostvars(nodes)
    context["inventory_hostname"] = "pg-node1"
    context["ansible_host"] = "10.20.0.11"
    context["major_version"] = "16"
    context["edition"] = "be"
    context["postgresql_vendor"] = "tantordb"
    context["ansible_facts"] = {
        "os_family": "Debian",
        "default_ipv4": {"address": "10.20.0.11", "interface": "eth0"},
        "fqdn": "pg-node1",
    }

    try:
        rendered = render_template(tmpl, context)
    except Exception as e:
        fail(f"Render error: {e}")
        return

    # Check no undefined variables
    if "{{" in rendered and "}}" in rendered:
        undefined_vars = re.findall(r"\{\{\s*(\w+)", rendered)
        real_undefined = [v for v in undefined_vars if v not in ("endif", "endfor", "else", "if", "for")]
        if real_undefined:
            fail(f"Unresolved variables in output: {set(real_undefined)}")
        else:
            ok("No undefined variables in patroni.yml.j2 output")
    else:
        ok("No undefined variables in patroni.yml.j2 output")

    # Check key fields are present
    key_fields = ["scope:", "name:", "restapi:", "etcd3:", "bootstrap:"]
    for field in key_fields:
        if field in rendered:
            ok(f"Key field '{field}' present in rendered patroni.yml")
        else:
            fail(f"Key field '{field}' MISSING from rendered patroni.yml")

    # Validate YAML output
    try:
        parsed = yaml.safe_load(rendered)
        expected = {
            "scope": context["patroni_scope"],
            "name": context["patroni_name"],
        }
        for key, value in expected.items():
            if parsed.get(key) == value:
                ok(f"Patroni {key} matches fixture")
            else:
                fail(f"Patroni {key} does not match fixture")
        if parsed["restapi"]["listen"] != context["patroni_restapi_listen"]:
            fail("Patroni REST API listen address does not match fixture")
        if parsed["log"]["dir"] != context["patroni_log_dir"]:
            fail("Patroni log directory does not match fixture")
        ok("Rendered patroni.yml is valid YAML")
    except yaml.YAMLError as e:
        fail(f"Rendered patroni.yml is not valid YAML: {e}")


def test_etcd_conf_template():
    """Test rendering etcd.conf.j2."""
    print("\n[Test] etcd.conf.j2 rendering")
    tmpl = ROLES_DIR / "etcd" / "templates" / "etcd.conf.j2"
    if not tmpl.exists():
        fail("etcd.conf.j2 not found")
        return

    group_vars = load_group_vars()
    fixture = load_fixture("etcd_vars.yml")
    context = {**group_vars, **fixture}

    nodes = ["pg-node1", "pg-node2", "pg-node3"]
    context["groups"] = {"all": nodes, "inv_etcd": nodes, "inv_cluster": nodes}
    context["hostvars"] = make_hostvars(nodes)
    context["inventory_hostname"] = "pg-node1"
    context["unified_hostname"] = "pg-node1"
    context["ansible_facts"] = {"default_ipv4": {"address": "10.20.0.11", "interface": "eth0"}}

    # etcd-specific computed vars
    context["etcd_listen_public"] = "0.0.0.0"
    context["etcd_listen_cluster"] = "0.0.0.0"
    context["etcd_address_public"] = "10.20.0.11"
    context["etcd_address_cluster"] = "10.20.0.11"
    context["etcd_initial_cluster_state"] = "new"
    context["etcd_use_initial_token"] = True
    context["etcd_pki_cert_dest"] = "/opt/tantor/var/lib/etcd/pg-cluster.pki/pg-node1.pem"
    context["etcd_pki_key_dest"] = "/opt/tantor/var/lib/etcd/pg-cluster.pki/pg-node1-key.pem"
    context["etcd_pki_ca_cert_dest"] = "/opt/tantor/var/lib/etcd/pg-cluster.pki/ca.pem"

    try:
        rendered = render_template(tmpl, context)
    except Exception as e:
        fail(f"Render error: {e}")
        return

    # Check key etcd config lines
    expected_patterns = [
        r'ETCD_NAME=',
        r'ETCD_DATA_DIR=',
        r'ETCD_LISTEN_CLIENT_URLS=',
        r'ETCD_INITIAL_CLUSTER=',
    ]
    for pattern in expected_patterns:
        if re.search(pattern, rendered):
            ok(f"Pattern '{pattern}' found in etcd.conf")
        else:
            fail(f"Pattern '{pattern}' NOT found in etcd.conf")

    # Check TLS section
    if "ETCD_CERT_FILE" in rendered:
        ok("TLS configuration present in etcd.conf")
    else:
        fail("TLS configuration MISSING from etcd.conf")


def test_haproxy_cfg_template():
    """Test rendering haproxy.cfg.j2."""
    print("\n[Test] haproxy.cfg.j2 rendering")
    tmpl = ROLES_DIR / "haproxy" / "templates" / "haproxy.cfg.j2"
    if not tmpl.exists():
        fail("haproxy.cfg.j2 not found")
        return

    group_vars = load_group_vars()
    fixture = load_fixture("haproxy_vars.yml")
    context = {**group_vars, **fixture}

    nodes = ["pg-node1", "pg-node2", "pg-node3"]
    context["groups"] = {"all": nodes, "inv_pg": nodes}
    context["hostvars"] = make_hostvars(nodes)

    try:
        rendered = render_template(tmpl, context)
    except Exception as e:
        fail(f"Render error: {e}")
        return

    # Check backends are generated for each node
    for node in nodes:
        if f"server {node}" in rendered:
            ok(f"HAProxy backend for '{node}' present")
        else:
            fail(f"HAProxy backend for '{node}' MISSING")

    # Check stats listener
    if "listen stats" in rendered and "bind *:7000" in rendered:
        ok("HAProxy stats listener configured")
    else:
        fail("HAProxy stats listener MISSING")


def test_keepalived_conf_template():
    """Test rendering keepalived.conf.j2."""
    print("\n[Test] keepalived.conf.j2 rendering")
    tmpl = ROLES_DIR / "keepalived" / "templates" / "keepalived.conf.j2"
    if not tmpl.exists():
        fail("keepalived.conf.j2 not found")
        return

    group_vars = load_group_vars()
    fixture = load_fixture("keepalived_vars.yml")
    context = {**group_vars, **fixture}

    nodes = ["pg-node1", "pg-node2", "pg-node3"]
    context["groups"] = {"all": nodes, "inv_pg": nodes, "inv_keepalived": nodes}
    context["hostvars"] = make_hostvars(nodes)
    context["inventory_hostname"] = "pg-node1"
    context["ansible_facts"] = {"default_ipv4": {"address": "10.20.0.11", "interface": "eth0"}}

    try:
        rendered = render_template(tmpl, context)
    except Exception as e:
        fail(f"Render error: {e}")
        return

    if "vrrp_script" in rendered:
        ok("keepalived vrrp_script section present")
    else:
        fail("keepalived vrrp_script section MISSING")

    if "vrrp_instance" in rendered:
        ok("keepalived vrrp_instance section present")
    else:
        fail("keepalived vrrp_instance section MISSING")


def test_pgbouncer_ini_template():
    """Test rendering pgbouncer.ini.j2."""
    print("\n[Test] pgbouncer.ini.j2 rendering")
    tmpl = ROLES_DIR / "pgbouncer" / "templates" / "pgbouncer.ini.j2"
    if not tmpl.exists():
        fail("pgbouncer.ini.j2 not found")
        return

    group_vars = load_group_vars()
    fixture = load_fixture("pgbouncer_vars.yml")
    context = {**group_vars, **fixture}

    nodes = ["pg-node1", "pg-node2", "pg-node3"]
    context["groups"] = {"all": nodes, "inv_cluster": nodes}
    context["hostvars"] = make_hostvars(nodes)
    context["major_version"] = "16"

    try:
        rendered = render_template(tmpl, context)
    except Exception as e:
        fail(f"Render error: {e}")
        return

    if "[databases]" in rendered and "[pgbouncer]" in rendered:
        ok("pgbouncer.ini sections present")
    else:
        fail("pgbouncer.ini sections MISSING")

    if "scram-sha-256" in rendered:
        ok("pgbouncer.ini uses scram-sha-256 auth for PG16+")
    else:
        fail("pgbouncer.ini must use scram-sha-256 for PG16")


def test_etcd_service_template():
    """Test rendering etcd-tantor.service.j2."""
    print("\n[Test] etcd-tantor.service.j2 rendering")
    tmpl = ROLES_DIR / "etcd" / "templates" / "etcd-tantor.service.j2"
    if not tmpl.exists():
        fail("etcd-tantor.service.j2 not found")
        return

    group_vars = load_group_vars()
    fixture = load_fixture("etcd_vars.yml")
    context = {**group_vars, **fixture}
    context["etcd_user"] = "etcd"

    try:
        rendered = render_template(tmpl, context)
    except Exception as e:
        fail(f"Render error: {e}")
        return

    if "[Unit]" in rendered and "[Service]" in rendered and "[Install]" in rendered:
        ok("etcd service has [Unit]/[Service]/[Install] sections")
    else:
        fail("etcd service missing systemd sections")

    if "ExecStart=" in rendered:
        ok("etcd service has ExecStart directive")
    else:
        fail("etcd service missing ExecStart")

    if "User= etcd" in rendered or "User=etcd" in rendered:
        ok("etcd service has correct User")
    else:
        fail("etcd service missing or incorrect User")


def test_patroni_service_template():
    """Test rendering patroni-tantor.service.j2."""
    print("\n[Test] patroni-tantor.service.j2 rendering")
    tmpl = ROLES_DIR / "patroni" / "templates" / "patroni-tantor.service.j2"
    if not tmpl.exists():
        fail("patroni-tantor.service.j2 not found")
        return

    group_vars = load_group_vars()
    fixture = load_fixture("patroni_vars.yml")
    context = {**group_vars, **fixture}
    context["patroni_system_user"] = "postgres"
    context["patroni_system_group"] = "postgres"
    context["patroni_exec_start_pre"] = "/bin/mkdir -m 2750 -p /var/run/postgresql/16-main.pg_stat_tmp"
    context["patroni_bin_dir"] = "/usr/bin"
    context["patroni_config_dir"] = "/opt/tantor/etc/patroni"
    context["patroni_name"] = "pg-node1"
    context["inventory_hostname"] = "pg-node1"

    try:
        rendered = render_template(tmpl, context)
    except Exception as e:
        fail(f"Render error: {e}")
        return

    if "[Unit]" in rendered and "[Service]" in rendered:
        ok("patroni service has [Unit]/[Service] sections")
    else:
        fail("patroni service missing systemd sections")

    if "ExecStart=" in rendered and "patroni" in rendered:
        ok("patroni service has ExecStart with patroni")
    else:
        fail("patroni service missing ExecStart")

    if "User=postgres" in rendered:
        ok("patroni service has correct User")
    else:
        fail("patroni service missing or incorrect User")

    if "ExecStartPre=" in rendered:
        ok("patroni service has ExecStartPre directive")
    else:
        fail("patroni service missing ExecStartPre")


def test_patroni_watchdog_service_template():
    """Test rendering patroni-watchdog.service.j2."""
    print("\n[Test] patroni-watchdog.service.j2 rendering")
    tmpl = ROLES_DIR / "patroni" / "templates" / "patroni-watchdog.service.j2"
    if not tmpl.exists():
        fail("patroni-watchdog.service.j2 not found")
        return

    try:
        rendered = render_template(tmpl, {})
    except Exception as e:
        fail(f"Render error: {e}")
        return

    if "[Unit]" in rendered and "[Service]" in rendered:
        ok("patroni-watchdog service has [Unit]/[Service] sections")
    else:
        fail("patroni-watchdog service missing systemd sections")

    if "softdog" in rendered:
        ok("patroni-watchdog service loads softdog module")
    else:
        fail("patroni-watchdog service missing softdog reference")


def test_pgbouncer_service_template():
    """Test rendering pgbouncer.service.j2."""
    print("\n[Test] pgbouncer.service.j2 rendering")
    tmpl = ROLES_DIR / "pgbouncer" / "templates" / "pgbouncer.service.j2"
    if not tmpl.exists():
        fail("pgbouncer.service.j2 not found")
        return

    group_vars = load_group_vars()
    fixture = load_fixture("pgbouncer_vars.yml")
    context = {**group_vars, **fixture}
    context["pgbouncer_conf_file"] = "/opt/tantor/etc/pgbouncer/pgbouncer.ini"

    try:
        rendered = render_template(tmpl, context)
    except Exception as e:
        fail(f"Render error: {e}")
        return

    if "[Unit]" in rendered and "[Service]" in rendered:
        ok("pgbouncer service has [Unit]/[Service] sections")
    else:
        fail("pgbouncer service missing systemd sections")

    if "ExecStart=" in rendered and "pgbouncer" in rendered:
        ok("pgbouncer service has ExecStart with pgbouncer")
    else:
        fail("pgbouncer service missing ExecStart")

    if "BOUNCERCONF=" in rendered:
        ok("pgbouncer service has BOUNCERCONF environment")
    else:
        fail("pgbouncer service missing BOUNCERCONF")


def test_walg_json_template():
    """Test rendering walg.json.j2 with S3 storage."""
    print("\n[Test] walg.json.j2 rendering (S3)")
    tmpl = ROLES_DIR / "patroni" / "templates" / "walg.json.j2"
    if not tmpl.exists():
        fail("walg.json.j2 not found")
        return

    group_vars = load_group_vars()
    fixture = load_fixture("patroni_vars.yml")
    context = {**group_vars, **fixture}
    context["postgresql_vendor"] = "classic"
    context["patroni_boostrap_method_walg_storage"] = "s3"
    context["patroni_boostrap_method_walg_s3_username"] = "test_user"
    context["patroni_boostrap_method_walg_s3_password"] = "test_pass"
    context["patroni_boostrap_method_walg_s3_bucket"] = "test-bucket"
    context["patroni_boostrap_method_walg_s3_region"] = "ru-central1"
    context["patroni_pg_data_dir"] = "/var/lib/postgresql/data"
    context["major_version"] = "16"
    context["inventory_hostname"] = "pg-node1"
    context["patroni_pg_port"] = 5432
    context["ansible_facts"] = {"os_family": "Debian"}

    try:
        rendered = render_template(tmpl, context)
    except Exception as e:
        fail(f"Render error: {e}")
        return

    try:
        parsed = json.loads(rendered)
        ok("walg.json renders as valid JSON")
    except json.JSONDecodeError:
        fail("walg.json does not render as valid JSON")
        return

    if parsed.get("AWS_ACCESS_KEY_ID") == "test_user":
        ok("walg.json has correct AWS_ACCESS_KEY_ID")
    else:
        fail("walg.json has incorrect or missing AWS_ACCESS_KEY_ID")

    if "WALE_S3_PREFIX" in parsed:
        ok("walg.json has WALE_S3_PREFIX")
    else:
        fail("walg.json missing WALE_S3_PREFIX")

    if "PGDATA" in parsed:
        ok("walg.json has PGDATA key")
    else:
        fail("walg.json missing PGDATA key")


def test_bootstrap_script_template():
    """Test rendering patroni_custom_bootstrap_script.sh.j2."""
    print("\n[Test] patroni_custom_bootstrap_script.sh.j2 rendering")
    tmpl = ROLES_DIR / "patroni" / "templates" / "patroni_custom_bootstrap_script.sh.j2"
    if not tmpl.exists():
        fail("patroni_custom_bootstrap_script.sh.j2 not found")
        return

    group_vars = load_group_vars()
    fixture = load_fixture("patroni_vars.yml")
    context = {**group_vars, **fixture}
    context["postgresql_vendor"] = "classic"
    context["patroni_pg_data_dir"] = "/var/lib/postgresql/data"
    context["patroni_pg_bin_dir"] = "/usr/lib/postgresql/16/bin"
    context["major_version"] = "16"
    context["inventory_hostname"] = "pg-node1"
    context["ansible_facts"] = {"os_family": "Debian"}

    try:
        rendered = render_template(tmpl, context)
    except Exception as e:
        fail(f"Render error: {e}")
        return

    if rendered.startswith("#!/bin/bash"):
        ok("bootstrap script has shebang")
    else:
        fail("bootstrap script missing shebang")

    if "wal-g" in rendered:
        ok("bootstrap script references wal-g")
    else:
        fail("bootstrap script missing wal-g reference")

    if "initdb" in rendered:
        ok("bootstrap script has initdb for no-backup case")
    else:
        fail("bootstrap script missing initdb")

    if re.search(r'^pgdata_dir="[^"\n]+"', rendered, re.MULTILINE):
        ok("bootstrap script sets pgdata_dir variable")
    else:
        fail("bootstrap script missing pgdata_dir")


def main():
    print("=" * 60)
    print("pg_cluster — Jinja2 Template Rendering Tests")
    print("=" * 60)

    test_patroni_yml_template()
    test_etcd_conf_template()
    test_haproxy_cfg_template()
    test_keepalived_conf_template()
    test_pgbouncer_ini_template()
    test_etcd_service_template()
    test_patroni_service_template()
    test_patroni_watchdog_service_template()
    test_pgbouncer_service_template()
    test_walg_json_template()
    test_bootstrap_script_template()

    print("\n" + "=" * 60)
    print(f"Results: {GREEN}{passed} passed{RESET}, {RED}{failed} failed{RESET}, {YELLOW}{warnings} warnings{RESET}")
    print("=" * 60)

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
