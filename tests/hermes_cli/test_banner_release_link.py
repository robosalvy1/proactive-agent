"""The banner version title links to this project's GitHub releases, not the upstream repo."""

from hermes_cli import banner, source_check


def test_release_link_points_at_project_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(banner, "_latest_release_cache", None)
    monkeypatch.setattr(source_check, "_git_stdout", lambda args, **kw: "v1.2.3")

    tag, url = banner.get_latest_release_tag(repo_dir=tmp_path)

    assert tag == "v1.2.3"
    assert url == "https://github.com/robosalvy1/proactive-agent/releases/tag/v1.2.3"
    assert "NousResearch" not in url
