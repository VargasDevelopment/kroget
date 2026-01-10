import json

from typer.testing import CliRunner

from kroget.cli import app


def test_openapi_check_ok():
    runner = CliRunner()
    result = runner.invoke(app, ["openapi", "check"])
    assert result.exit_code == 0
    assert "OK" in result.output


def test_openapi_check_missing(tmp_path):
    spec_dir = tmp_path / "openapi"
    spec_dir.mkdir()

    minimal = {"openapi": "3.0.3", "paths": {"/v1/products": {"get": {}}}}
    (spec_dir / "kroger-products-openapi.json").write_text(
        json.dumps(minimal), encoding="utf-8"
    )

    result = CliRunner().invoke(app, ["openapi", "check", "--dir", str(spec_dir)])
    assert result.exit_code == 1
    assert "missing" in result.output
