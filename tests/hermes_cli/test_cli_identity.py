"""The CLI agent name comes from the profile's AGENT_NAME.txt, then the skin, then Hermes."""

from hermes_cli import cli_identity, skin_engine


def test_profile_name_file_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "AGENT_NAME.txt").write_text("  Mira  \nignored\n", encoding="utf-8")

    assert cli_identity.get_agent_name() == "Mira"


def test_blank_name_file_falls_back_to_skin_branding(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "AGENT_NAME.txt").write_text("   \n", encoding="utf-8")

    class _Skin:
        def get_branding(self, key, default):
            return "Skinny" if key == "agent_name" else default

    monkeypatch.setattr(skin_engine, "get_active_skin", lambda: _Skin())

    assert cli_identity.get_agent_name() == "Skinny"


def test_missing_name_and_skin_falls_back_to_hermes(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    def _broken():
        raise RuntimeError("no skin")

    monkeypatch.setattr(skin_engine, "get_active_skin", _broken)

    assert cli_identity.get_agent_name() == "Hermes"
