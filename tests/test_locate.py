import time

from sc2copilot.replay.locate import find_replay_dirs, newest_replay


def make_replay_tree(home):
    d = home / "Documents" / "StarCraft II" / "Accounts" / "123" / "1-S2-1-999" / "Replays" / "Multiplayer"
    d.mkdir(parents=True)
    return d


def test_find_replay_dirs(tmp_path):
    d = make_replay_tree(tmp_path)
    assert find_replay_dirs(home=tmp_path) == [d]


def test_find_replay_dirs_empty(tmp_path):
    assert find_replay_dirs(home=tmp_path) == []


def test_newest_replay_by_mtime(tmp_path):
    d = make_replay_tree(tmp_path)
    old = d / "old.SC2Replay"
    new = d / "new.SC2Replay"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    past = time.time() - 100
    import os

    os.utime(old, (past, past))
    assert newest_replay([d]) == new


def test_newest_replay_none_when_empty(tmp_path):
    d = make_replay_tree(tmp_path)
    assert newest_replay([d]) is None
