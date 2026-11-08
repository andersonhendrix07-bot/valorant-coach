import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIX = Path(__file__).parent / "fixtures"
ME = "me-puuid"


def load(name):
    return json.loads((FIX / name).read_text())


@pytest.fixture
def match_a():
    return load("match_a_win_jett.json")


@pytest.fixture
def match_b():
    return load("match_b_loss_sova_ot.json")


@pytest.fixture
def mmr_hist():
    return load("mmr_history.json")
