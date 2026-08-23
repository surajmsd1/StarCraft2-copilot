from sc2copilot.practice.announce import Announcer, humanize, speak_time


def test_humanize_splits_camel_case():
    assert humanize("SpawningPool") == "Spawning Pool"
    assert humanize("RoachWarren") == "Roach Warren"
    assert humanize("CommandCenter") == "Command Center"


def test_humanize_keeps_acronyms_and_plain_text():
    assert humanize("SCV") == "SCV"
    assert humanize("Send proxy SCVs") == "Send proxy SCVs"
    assert humanize("Supply Depot") == "Supply Depot"


def test_speak_time():
    assert speak_time(48) == "48 seconds"
    assert speak_time(95) == "1 35"
    assert speak_time(120) == "2 minutes"
    assert speak_time(60) == "1 minute"


def test_announce_sink_gets_display_text_not_spoken():
    lines = []
    announcer = Announcer(use_tts=False, sink=lines.append)
    announcer.announce(95, "SpawningPool at 1:35", spoken="Spawning Pool, 1 35")
    assert lines == ["[1:35] SpawningPool at 1:35"]


def test_announce_spoken_dash_means_silent():
    # spoken="-" displays but never queues speech; with tts off this is a
    # no-crash check that the contract is accepted.
    lines = []
    announcer = Announcer(use_tts=False, sink=lines.append)
    announcer.announce(0, "Practicing: some build (16 cues)", spoken="-")
    assert len(lines) == 1
