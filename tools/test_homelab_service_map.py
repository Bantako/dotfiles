import importlib.util
import pathlib
import tempfile
import unittest
from unittest.mock import patch


MODULE_PATH = pathlib.Path(__file__).with_name("homelab_service_map.py")
SPEC = importlib.util.spec_from_file_location("homelab_service_map", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load {MODULE_PATH}")
service_map = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(service_map)


class ParseDockerInspectTests(unittest.TestCase):
    def test_groups_services_by_compose_project_with_state(self):
        inventory = service_map.parse_docker_inspect(
            '[{"Config":{"Labels":{"com.docker.compose.project":"paperless",'
            '"com.docker.compose.service":"webserver"}},"State":{"Status":"running"}},'
            '{"Config":{"Labels":{"com.docker.compose.project":"paperless",'
            '"com.docker.compose.service":"db"}},"State":{"Status":"exited"}}]'
        )

        self.assertEqual(
            inventory,
            {"paperless": [("db", "exited"), ("webserver", "running")]},
        )

    def test_ignores_unlabelled_containers(self):
        inventory = service_map.parse_docker_inspect(
            '[{"Config":{"Labels":{}},"State":{"Status":"running"}}]'
        )

        self.assertEqual(inventory, {})


class ProbeNasTests(unittest.TestCase):
    def test_returns_inventory_error_for_invalid_docker_json(self):
        with patch.object(service_map, "run", return_value="not-json"):
            observed, error = service_map.probe_nas()

        self.assertEqual(observed, {})
        self.assertIsNotNone(error)

    def test_returns_inventory_error_for_non_array_docker_json(self):
        with patch.object(service_map, "run", return_value="{}"):
            observed, error = service_map.probe_nas()

        self.assertEqual(observed, {})
        self.assertIsNotNone(error)

    def test_returns_inventory_error_for_non_object_docker_item(self):
        with patch.object(service_map, "run", return_value="[null]"):
            observed, error = service_map.probe_nas()

        self.assertEqual(observed, {})
        self.assertIsNotNone(error)


class ProbeSystemdTests(unittest.TestCase):
    def test_marks_incomplete_unit_properties_as_unobserved(self):
        with patch.object(
            service_map,
            "run",
            return_value="LoadState=loaded\nActiveState=active\n",
        ):
            observed = service_map.probe_systemd({"incomplete.service": {}})

        self.assertEqual(observed, {"incomplete.service": "未観測"})

    def test_marks_not_found_unit_as_unobserved(self):
        with patch.object(
            service_map,
            "run",
            return_value="LoadState=not-found\nActiveState=inactive\nSubState=dead\n",
        ):
            observed = service_map.probe_systemd({"renamed.service": {}})

        self.assertEqual(observed, {"renamed.service": "未観測（unit不存在）"})

    def test_keeps_existing_unit_state(self):
        with patch.object(
            service_map,
            "run",
            return_value="LoadState=loaded\nActiveState=active\nSubState=running\n",
        ):
            observed = service_map.probe_systemd({"known.service": {}})

        self.assertEqual(observed, {"known.service": "active (running)"})


class RenderMarkdownTests(unittest.TestCase):
    def test_shows_stopped_and_unregistered_projects(self):
        manifest = {
            "nas": {
                "paperless": {
                    "layer": "個人データの正本",
                    "purpose": "書類を保管・検索する",
                    "source": "NAS ~/services/paperless",
                    "observe": "container health + Homepage",
                    "change_check": "DB backup と HTTP health",
                },
            },
            "ser7": {},
        }

        rendered = service_map.render_markdown(
            manifest,
            observed_nas={
                "paperless": [("db", "running")],
                "filebrowser": [("filebrowser", "exited")],
            },
            observed_ser7={},
            generated_at="2026-07-13T12:00:00+09:00",
        )

        self.assertIn("paperless | 稼働: db", rendered)
        self.assertIn("## 未登録のNAS Composeプロジェクト", rendered)
        self.assertIn("filebrowser | 停止: filebrowser", rendered)

    def test_records_nas_inventory_error(self):
        rendered = service_map.render_markdown(
            {"nas": {}, "ser7": {}},
            observed_nas={},
            observed_ser7={},
            generated_at="2026-07-13T12:00:00+09:00",
            nas_error="ssh failed",
        )

        self.assertIn("## NAS Docker観測の取得失敗", rendered)
        self.assertIn("ssh failed", rendered)


class ManifestValidationTests(unittest.TestCase):
    def test_reports_missing_manifest_field_with_entry_path(self):
        manifest = {
            "nas": {
                "paperless": {
                    "layer": "個人データの正本",
                    "purpose": "書類を保管・検索する",
                    "source": "NAS ~/services/paperless",
                    "observe": "container health + Homepage",
                },
            },
            "ser7": {},
        }

        with self.assertRaisesRegex(ValueError, "nas.paperless.change_check"):
            service_map.validate_manifest(manifest)


class MainTests(unittest.TestCase):
    def test_exits_nonzero_when_nas_project_is_unregistered(self):
        with tempfile.TemporaryDirectory() as directory:
            directory_path = pathlib.Path(directory)
            manifest = directory_path / "manifest.json"
            output = directory_path / "map.md"
            manifest.write_text('{"nas": {}, "ser7": {}}')

            with (
                patch.object(
                    service_map,
                    "probe_nas",
                    return_value=({"unknown": [("app", "running")]}, None),
                ),
                patch.object(service_map, "probe_systemd", return_value={}),
                patch(
                    "sys.argv",
                    [
                        "homelab_service_map.py",
                        "--manifest",
                        str(manifest),
                        "--output",
                        str(output),
                    ],
                ),
            ):
                self.assertEqual(service_map.main(), 1)

            self.assertIn("未登録のNAS Composeプロジェクト", output.read_text())


if __name__ == "__main__":
    unittest.main()