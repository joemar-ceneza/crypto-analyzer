"""Tests for startup log rotation (multi-process-safe by design)."""

import os

import config
import utils


def _point_log_at(tmp_path, monkeypatch, size_limit: int = 100):
    log_file = str(tmp_path / "automation.log")
    monkeypatch.setattr(config, "LOG_FILE", log_file)
    monkeypatch.setattr(config, "LOG_MAX_BYTES", size_limit)
    monkeypatch.setattr(config, "LOG_BACKUP_COUNT", 3)
    return log_file


def test_small_log_is_left_alone(tmp_path, monkeypatch):
    log_file = _point_log_at(tmp_path, monkeypatch)
    with open(log_file, "w", encoding="utf-8") as handle:
        handle.write("short")
    utils._rotate_log_if_needed()
    assert os.path.exists(log_file)
    assert not os.path.exists(log_file + ".1")


def test_oversized_log_rotates_to_backup(tmp_path, monkeypatch):
    log_file = _point_log_at(tmp_path, monkeypatch, size_limit=10)
    with open(log_file, "w", encoding="utf-8") as handle:
        handle.write("x" * 50)
    utils._rotate_log_if_needed()
    assert not os.path.exists(log_file)          # current became .1
    assert os.path.exists(log_file + ".1")


def test_backups_shift_and_oldest_drops(tmp_path, monkeypatch):
    log_file = _point_log_at(tmp_path, monkeypatch, size_limit=10)
    with open(log_file, "w", encoding="utf-8") as handle:
        handle.write("x" * 50)
    for index in (1, 2, 3):
        with open(f"{log_file}.{index}", "w", encoding="utf-8") as handle:
            handle.write(f"backup {index}")

    utils._rotate_log_if_needed()
    # current -> .1, old .1 -> .2, old .2 -> .3, old .3 dropped
    with open(log_file + ".1", encoding="utf-8") as handle:
        assert handle.read() == "x" * 50
    with open(log_file + ".2", encoding="utf-8") as handle:
        assert handle.read() == "backup 1"
    with open(log_file + ".3", encoding="utf-8") as handle:
        assert handle.read() == "backup 2"
    assert not os.path.exists(log_file + ".4")


def test_missing_log_is_not_an_error(tmp_path, monkeypatch):
    _point_log_at(tmp_path, monkeypatch)
    utils._rotate_log_if_needed()  # must simply return


def test_locked_log_postpones_rotation(tmp_path, monkeypatch):
    """
    The reason rotation lives at startup: on Windows a file another process
    holds open cannot be renamed. That must postpone rotation, never crash or
    spam — the log keeps working and a later run rotates it.
    """
    log_file = _point_log_at(tmp_path, monkeypatch, size_limit=10)
    with open(log_file, "w", encoding="utf-8") as handle:
        handle.write("x" * 50)
        handle.flush()
        # While the handle is open, Windows blocks the rename inside.
        utils._rotate_log_if_needed()
    if os.name == "nt":
        assert os.path.exists(log_file)  # rotation postponed, not forced
    # On any OS: no exception is the contract.
