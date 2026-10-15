"""Messaging offer persistence and profile-local identity destinations."""

from hermes_yaml import safe_dump, safe_load

from gateway.messaging_onboarding import (
    MESSAGING_PERSONALIZATION_FLAG,
    first_messaging_note,
    personalization_directive,
)


def test_cli_offer_does_not_consume_messaging_offer(tmp_path):
    path = tmp_path / "config.yaml"
    config = {"model": {"default": "test"}, "onboarding": {
        "seen": {"profile_build_offered": True},
    }}
    path.write_text(safe_dump(config))

    assert first_messaging_note(config, path) == personalization_directive(tmp_path)
    saved = safe_load(path.read_text())
    assert saved["model"] == config["model"]
    assert saved["onboarding"]["seen"]["profile_build_offered"] is True
    assert saved["onboarding"]["seen"][MESSAGING_PERSONALIZATION_FLAG] is True
    assert first_messaging_note(saved, path) is None


def test_each_profile_has_its_own_offer_and_identity_paths(tmp_path):
    for profile in ("first", "second"):
        home = tmp_path / profile
        home.mkdir()
        note = first_messaging_note({}, home / "config.yaml")
        assert note is not None
        for name in ("USER_NAME.txt", "AGENT_NAME.txt", "SOUL.md"):
            assert str(home / name) in note
        assert first_messaging_note(safe_load((home / "config.yaml").read_text()), home / "config.yaml") is None


def test_failed_latch_does_not_start_an_untracked_offer(tmp_path, monkeypatch):
    def fail_write(*_args):
        raise OSError("synthetic write failure")

    monkeypatch.setattr("hermes_cli.config.atomic_config_write", fail_write)
    assert first_messaging_note({}, tmp_path / "config.yaml") is None
