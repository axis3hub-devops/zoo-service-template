import importlib.util
import sys
import types
from pathlib import Path

import pytest
from cookiecutter.main import cookiecutter


def _mock_runtime_dependencies():
    if "zoo_calrissian_runner" not in sys.modules:
        zcr_module = types.ModuleType("zoo_calrissian_runner")
        zcr_module.ExecutionHandler = type("ExecutionHandler", (), {})
        zcr_module.ZooCalrissianRunner = type("ZooCalrissianRunner", (), {})
        sys.modules["zoo_calrissian_runner"] = zcr_module

    if "zoo" not in sys.modules:
        zoo_module = types.ModuleType("zoo")
        zoo_module.SERVICE_SUCCEEDED = 3
        zoo_module.SERVICE_FAILED = 4
        zoo_module.update_status = lambda conf, progress: None
        zoo_module._ = lambda message: message
        sys.modules["zoo"] = zoo_module


@pytest.fixture(scope="session")
def rendered_service_module(tmp_path_factory):
    template_root = Path(__file__).resolve().parent.parent
    output_root = tmp_path_factory.mktemp("cookiecutter-render")
    config_path = output_root / "cookiecutter-test-config.yaml"
    config_path.write_text(
        f"cookiecutters_dir: '{output_root / '.cookiecutters'}'\n"
        f"replay_dir: '{output_root / '.cookiecutter_replay'}'\n"
        "default_context: {}\n"
        "abbreviations:\n"
        "  gh: https://github.com/{0}.git\n"
        "  gl: https://gitlab.com/{0}.git\n"
        "  bb: https://bitbucket.org/{0}.git\n"
    )
    rendered_project = Path(
        cookiecutter(
            str(template_root),
            no_input=True,
            output_dir=str(output_root),
            config_file=str(config_path),
            extra_context={
                "workflow_id": "test-workflow",
                "service_name": "rendered_service",
            },
        )
    )
    service_path = rendered_project / "service.py"

    _mock_runtime_dependencies()

    sys.path.insert(0, str(rendered_project))
    try:
        spec = importlib.util.spec_from_file_location(
            "rendered_service_module",
            service_path,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Failed to load generated service module from {service_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if str(rendered_project) in sys.path:
            sys.path.remove(str(rendered_project))
