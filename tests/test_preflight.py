import subprocess

from pptx import Presentation

import preflight


def _project_with_schemas(tmp_path):
    project = tmp_path / "project"
    (project / "specs").mkdir(parents=True)
    (project / "specs" / "spec.schema.json").write_text("{}")
    (project / "specs" / "deck.schema.json").write_text("{}")
    return project


def _template(tmp_path):
    template = tmp_path / "template.pptx"
    Presentation().save(template)
    return template


def test_preflight_proves_template_conversion_and_rasterization(tmp_path, monkeypatch):
    project = _project_with_schemas(tmp_path)
    template = _template(tmp_path)
    output_root = tmp_path / "run"
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[0:2] == ["docker", "run"]:
            (output_root / "preflight" / "template.pdf").write_bytes(b"pdf")
        elif command[0] == "pdftoppm":
            (output_root / "preflight" / "template_page.png").write_bytes(b"png")
        return subprocess.CompletedProcess(command, 0, "converted", "")

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)

    report = preflight.run_preflight(template, "docker", output_root,
                                     project_root=project)

    assert report["ok"] is True
    assert report["checks"]["schemas"]["ok"] is True
    assert report["checks"]["conversion"]["pdf_bytes"] == 3
    assert report["checks"]["rasterization"]["png_count"] == 1
    raster = next(command for command in calls if command[0] == "pdftoppm")
    assert raster[:5] == ["pdftoppm", "-f", "1", "-l", "1"]
    assert "-singlefile" in raster


def test_preflight_accepts_page_one_output_for_a_template_name_with_dots(tmp_path, monkeypatch):
    project = _project_with_schemas(tmp_path)
    template = tmp_path / "client.v1.pptx"
    Presentation().save(template)
    output_root = tmp_path / "run"

    def fake_run(command, **kwargs):
        work = output_root / "preflight"
        if command[0:2] == ["docker", "run"]:
            (work / "client.v1.pdf").write_bytes(b"pdf")
        elif command[0] == "pdftoppm":
            (work / "client.v1_page.png").write_bytes(b"png")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)

    report = preflight.run_preflight(template, "docker", output_root,
                                     project_root=project)

    assert report["ok"] is True
    assert report["checks"]["rasterization"]["pngs"] == [
        str(output_root / "preflight" / "client.v1_page.png")
    ]


def test_preflight_rejects_an_unreadable_template(tmp_path):
    project = _project_with_schemas(tmp_path)
    template = tmp_path / "not-a-presentation.pptx"
    template.write_text("not a zip file")

    report = preflight.run_preflight(template, "host", tmp_path / "run",
                                     project_root=project)

    assert report["ok"] is False
    assert report["checks"]["template"]["ok"] is False
    assert report["checks"]["conversion"]["ok"] is False


def test_preflight_reports_missing_schema_paths(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / "specs").mkdir(parents=True)
    template = _template(tmp_path)
    output_root = tmp_path / "run"

    def fake_run(command, **kwargs):
        if command[0] == "soffice":
            (output_root / "preflight" / "template.pdf").write_bytes(b"pdf")
        else:
            (output_root / "preflight" / "template_page-1.png").write_bytes(b"png")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)

    report = preflight.run_preflight(template, "host", output_root,
                                     project_root=project)

    assert report["ok"] is False
    assert report["checks"]["schemas"] == {
        "ok": False,
        "missing": [
            str(project / "specs" / "spec.schema.json"),
            str(project / "specs" / "deck.schema.json"),
        ],
    }


def test_preflight_captures_docker_connection_failure(tmp_path, monkeypatch):
    project = _project_with_schemas(tmp_path)
    template = _template(tmp_path)

    monkeypatch.setattr(
        preflight.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 1, "", "Cannot connect to the Docker daemon"),
    )

    report = preflight.run_preflight(template, "docker", tmp_path / "run",
                                     project_root=project)

    assert report["ok"] is False
    assert report["checks"]["conversion"]["stderr"] == "Cannot connect to the Docker daemon"
    assert report["checks"]["conversion"]["pdf_bytes"] == 0


def test_preflight_rejects_a_non_writable_output_root(tmp_path, monkeypatch):
    project = _project_with_schemas(tmp_path)
    template = _template(tmp_path)
    monkeypatch.setattr(preflight, "_check_output_root", lambda path: {
        "ok": False, "error": "Permission denied",
    })

    report = preflight.run_preflight(template, "host", tmp_path / "run",
                                     project_root=project)

    assert report["ok"] is False
    assert report["checks"]["output_root"] == {
        "ok": False, "error": "Permission denied",
    }
