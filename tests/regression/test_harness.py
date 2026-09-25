"""Regression tests for failure propagation and the validators themselves."""
import contextlib
import importlib.util
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ansible.errors import AnsibleUndefinedVariable

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


static = load('static_tests', 'tests/static/test_static.py')
templates = load('template_tests', 'tests/templates/test_templates.py')
matrix = load('matrix_runner', 'tests/run_version_matrix.py')


class HarnessTests(unittest.TestCase):
    def test_syntax_failure_reaches_make(self):
        result = subprocess.run(['make', 'syntax', 'ANSIBLE=false'], cwd=ROOT, capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_all_role_yaml_files_are_discovered(self):
        paths = static.yaml_files_under(ROOT / 'roles')
        self.assertIn(ROOT / 'roles/patroni/tasks/main.yml', paths)
        self.assertGreater(len(paths), 0)

    def test_nested_yaml_and_invalid_syntax(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'example/tasks/nested/broken.yaml'
            path.parent.mkdir(parents=True)
            path.write_text('broken: [')
            with patch.object(static, 'ROLES_DIR', root), patch.object(static, 'REPO_ROOT', root), patch.object(static, 'GROUP_VARS_DIR', root / 'vars'), patch.object(static, 'failed', 0):
                with contextlib.redirect_stdout(io.StringIO()):
                    static.test_yaml_valid()
                self.assertGreater(static.failed, 0)

    def test_nested_notify_and_listen(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'example/tasks').mkdir(parents=True)
            (root / 'example/handlers').mkdir()
            task = root / 'example/tasks/main.yaml'
            task.write_text('- block:\n    - notify: reload\n  rescue:\n    - notify: missing\n')
            (root / 'example/handlers/main.yml').write_text('- name: Restart service\n  listen: reload\n')
            with patch.object(static, 'ROLES_DIR', root), patch.object(static, 'failed', 0):
                with contextlib.redirect_stdout(io.StringIO()):
                    static.test_handlers_exist()
                self.assertEqual(static.failed, 1)

    def test_required_variable_is_not_silently_erased(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'required.j2'
            path.write_text('dir: {{ patroni_log_dir }}\n')
            with self.assertRaises(AnsibleUndefinedVariable):
                templates.render_template(path, {})

    def test_ansible_filters_and_recursive_variables(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'filters.j2'
            path.write_text("{{ empty | default('fallback', true) }} {{ flag | bool }} {{ nested }}")
            rendered = templates.render_template(path, {'empty': '', 'flag': 'false', 'nested': '{{ value }}', 'value': 'resolved'})
            self.assertEqual(rendered, 'fallback False resolved')

    def test_matrix_builds_target_nodes_with_patroni_pin(self):
        entry = matrix.load_matrix()[0]
        with patch.object(matrix, 'run_cmd') as run:
            matrix.build_cluster(entry)
        args, kwargs = run.call_args
        self.assertEqual(args[0][-1], 'build')
        self.assertEqual(kwargs['env']['PATRONI_VERSION'], entry['patroni'])

    def test_matrix_timeout_is_a_failure(self):
        with patch.object(matrix, 'run_cmd', side_effect=subprocess.TimeoutExpired('make', 1)):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(matrix.run_tests(matrix.load_matrix()[0]), {'test': 'FAIL'})

    def test_controller_makefile_is_explicit(self):
        with patch.object(matrix, 'run_cmd') as run:
            with contextlib.redirect_stdout(io.StringIO()):
                matrix.run_tests(matrix.load_matrix()[0])
        self.assertIn('/opt/Makefile.controller', run.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
