from pathlib import Path
import re


IRIS_NEWS_NIX = Path(__file__).parents[1] / "nixos/modules/system/iris-news.nix"


def _service_environment(source: str, service: str) -> str:
    match = re.search(
        rf"systemd\.services\.{re.escape(service)}\s*=\s*\{{(?P<body>.*?)\n  \}};",
        source,
        re.DOTALL,
    )
    assert match is not None, f"missing {service} service"
    environment = re.search(r"environment\s*=\s*\{(?P<body>.*?)\n    \};", match["body"], re.DOTALL)
    assert environment is not None, f"missing environment for {service}"
    return environment["body"]


def test_build_and_api_use_distinct_uv_project_environments():
    source = IRIS_NEWS_NIX.read_text()

    build_environment = _service_environment(source, "iris-news-build")
    api_environment = _service_environment(source, "iris-news-api")

    build_path = re.search(r'UV_PROJECT_ENVIRONMENT\s*=\s*"([^"]+)";', build_environment)
    api_path = re.search(r'UV_PROJECT_ENVIRONMENT\s*=\s*"([^"]+)";', api_environment)

    assert build_path is not None
    assert api_path is not None
    assert build_path.group(1) != api_path.group(1)
