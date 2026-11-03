"""Public command reaches the existing CLI and preserves compatibility."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('name', ['tandem', 'hermes'])
@pytest.mark.parametrize('args, expected', [
    (['--help'], 'usage: tandem'),
    (['chat', '--help'], 'usage: tandem chat'),
    (['--version'], 'Agent v'),
    (['--invalid-tandem-option'], 'unrecognized arguments'),
])
def test_checkout_command(name, args, expected, tmp_path):
    env = dict(os.environ, HERMES_HOME=str(tmp_path / 'home'))
    result = subprocess.run(
        [sys.executable, str(ROOT / name), *args], env=env, cwd=tmp_path,
        capture_output=True, text=True, timeout=45, check=False,
    )
    assert result.returncode == (2 if args == ['--invalid-tandem-option'] else 0), result.stderr
    assert expected in result.stdout + result.stderr


def test_tandem_preserves_missing_plugin_guidance(monkeypatch):
    from hermes_cli._parser import _plugin_command_install_hint, _moved_command_hint
    from hermes_cli import memory_provider_migration
    from plugins import memory
    monkeypatch.setattr(memory, 'find_provider_dir', lambda name: None)
    monkeypatch.setattr(memory_provider_migration, 'catalog_install_hint',
                        lambda name, category: f'install {name}')
    assert _plugin_command_install_hint('tandem', 'honcho') == 'install honcho'
    assert _plugin_command_install_hint('tandem gateway', 'honcho') is None
    assert _moved_command_hint('tandem', 'spotify') == _moved_command_hint('hermes', 'spotify')


def test_uninstall_removes_owned_tandem_wrapper_only(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from hermes_cli import uninstall
    paths = Mock(side_effect=lambda path: tmp_path / str(path).lstrip('/'))
    paths.home.return_value = tmp_path
    monkeypatch.setattr(uninstall, 'Path', paths)
    wrapper = tmp_path / '.local/bin/tandem'
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text('#!/bin/sh\n# hermes_cli launcher\n', encoding='utf-8')
    assert uninstall.remove_wrapper_script() == [wrapper]
    wrapper.write_text('#!/bin/sh\nexec another-tool "$@"\n', encoding='utf-8')
    assert uninstall.remove_wrapper_script() == []
    assert wrapper.exists()
    # The published launcher names only the checkout's store launcher, not hermes_cli.
    wrapper.write_text(f'#!/bin/sh\nexec {tmp_path}/work/.hermes/bin/tandem "$@"\n', encoding='utf-8')
    assert uninstall.remove_wrapper_script() == [wrapper]
    wrapper.write_text('#!/bin/sh\nexec another-tool "$@"\n', encoding='utf-8')
    assert uninstall.remove_wrapper_script() == []
    assert wrapper.exists()


def test_completion_scripts_register_tandem_and_hermes():
    import argparse
    from hermes_cli.completion import generate_bash, generate_fish, generate_zsh
    parser = argparse.ArgumentParser(prog='tandem')
    parser.add_subparsers(dest='command').add_parser('chat', help='Chat')
    assert 'complete -F _hermes_completion hermes tandem' in generate_bash(parser)
    zsh = generate_zsh(parser)
    assert '#compdef hermes tandem' in zsh
    assert 'compdef _hermes hermes tandem' in zsh
    fish = generate_fish(parser).splitlines()
    for command in ('hermes', 'tandem'):
        assert f"complete -c {command} -f -n 'not __fish_seen_subcommand_from chat' -a chat -d 'Chat'" in fish


@pytest.mark.parametrize('argv', [
    ['tandem', 'gateway', 'run'],
    ['tandem.exe', 'gateway'],
    ['python3', '/v/bin/tandem', 'gateway', 'run'],
    ['hermes', 'gateway', 'run'],
])
def test_tandem_processes_are_recognised_as_hermes(argv):
    from hermes_cli.profiles import _is_hermes_argv
    assert _is_hermes_argv(argv)
    assert not _is_hermes_argv(['python3', '/v/bin/tandem-notes.py'])
    assert not _is_hermes_argv(['tandem-notes', 'gateway', '-p', 'work'])


def test_published_tandem_launcher_is_owned(tmp_path):
    from hermes_cli._launchers import _owns_launcher
    target = tmp_path / 'tandem'
    for name in ('tandem', 'hermes'):
        target.write_text(f'#!/bin/sh\nexec {tmp_path}/.hermes/bin/{name} "$@"\n', encoding='utf-8')
        assert _owns_launcher(target, tmp_path), name
    target.write_text('#!/bin/sh\nexec another-tool "$@"\n', encoding='utf-8')
    assert not _owns_launcher(target, tmp_path)


@pytest.mark.parametrize('command', [
    'tandem gateway run',
    'tandem.exe gateway run',
    '/usr/bin/python3 /repo/tandem gateway run',
    'tandem -p work gateway',
    'hermes gateway run',
])
def test_tandem_gateway_is_recognised_as_running_gateway(command):
    from gateway.status import looks_like_gateway_command_line
    assert looks_like_gateway_command_line(command)
    assert not looks_like_gateway_command_line('tandem chat')
