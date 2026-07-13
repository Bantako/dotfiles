import importlib.util
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).with_name("homelab_service_map.py")
SPEC = importlib.util.spec_from_file_location("homelab_service_map", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load {MODULE_PATH}")
service_map = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(service_map)


class ParseComposeInventoryTests(unittest.TestCase):
    def test_parses_docker_inspect_json(self):
        inventory = service_map.parse_docker_inspect(
            '[{"Name":"/paperless-web","Config":{"Labels":'
            '{"com.docker.compose.project":"paperless",'
            '"com.docker.compose.service":"webserver"}}}]'
        )

        self.assertEqual(inventory, {"paperless": ["webserver"]})

    def test_groups_services_by_compose_project(self):
        inventory = service_map.parse_compose_inventory(
            "/paperless-web\tproject=paperless\tservice=webserver\n"
            "/paperless-db\tproject=paperless\tservice=db\n"
            "/ntfy\tproject=ntfy\tservice=ntfy\n"
        )

        self.assertEqual(inventory["paperless"], ["db", "webserver"])
        self.assertEqual(inventory["ntfy"], ["ntfy"])

    def test_ignores_unlabelled_containers(self):
        inventory = service_map.parse_compose_inventory(
            "/legacy\tproject=<no value>\tservice=<no value>\n"
        )

        self.assertEqual(inventory, {})


class RenderMarkdownTests(unittest.TestCase):
    def test_marks_observed_projects_and_keeps_unavailable_distinct(self):
        manifest = {
            "nas": {
                "paperless": {
                    "layer": "個人データの正本",
                    "purpose": "書類を保管・検索する",
                    "source": "NAS ~/services/paperless",
                    "observe": "container health + Homepage",
                    "change_check": "DB backup と HTTP health",
                },
                "homebox": {
                    "layer": "候補・停止中",
                    "purpose": "資産管理の再評価候補",
                    "source": "NAS ~/services/homebox",
                    "observe": "未稼働",
                    "change_check": "要件確認後に判断",
                },
            },
            "ser7": {},
        }

        rendered = service_map.render_markdown(
            manifest,
            observed_nas={"paperless": ["db", "webserver"]},
            observed_ser7={"n8n.service": "active (running)"},
            generated_at="2026-07-13T12:00:00+09:00",
        )

        self.assertIn("paperless | 稼働: db, webserver", rendered)
        self.assertIn("homebox | 未観測", rendered)
        self.assertIn("生成日時: 2026-07-13T12:00:00+09:00", rendered)


if __name__ == "__main__":
    unittest.main()
