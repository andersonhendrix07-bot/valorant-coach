import json

import pandas as pd

import stats
import tips as tips_mod
import ui
from conftest import ME


def test_flat_removes_indentation_and_newlines():
    assert ui.flat("<div>\n    <b>x</b>\n\n    </div>") == "<div> <b>x</b> </div>"


def test_hero_escapes_user_text():
    html = ui.hero_html("<script>alert(1)</script>#NA1", "na", {"current": {"tier": {"name": "Gold 2"}, "rr": 55}},
                        {"wins": 3, "games": 5}, ["Win", "Loss"], "https://x/?a=1&b=2", 5)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "a=1&amp;b=2" in html
    assert "width:55%" in html            # RR progress bar
    assert html.count("vc-pill") == 2


def test_rr_progress():
    assert ui.rr_progress("Gold 2", 40) == 0.4
    assert ui.rr_progress("Immortal 1", 140) is None
    assert ui.rr_progress(None, 10) is None
    assert ui.rr_progress("Silver 1", 130) == 1.0


def test_tip_html_escapes_and_labels():
    t = tips_mod.Tip("Aim", "Title <b>", "data & numbers", "maybe", "do this", 1, 2, 0.5, 3)
    h = ui.tip_html(1, t, t.impact)
    assert "Title &lt;b&gt;" in h and "data &amp; numbers" in h
    assert "low sample" in h and "Interpretation:" in h and "width:100%" in h


def test_round_timeline(match_a):
    _, rdf = stats.build_frames([match_a], ME)
    h = ui.round_timeline_html(rdf)
    assert h.count('class="vc-r') == 14
    assert h.count(">FK<") == 2 and h.count(">FD<") == 1 and h.count(" half") == 1


def test_entity_cards(match_a, match_b):
    mdf, rdf = stats.build_frames([match_a, match_b], ME)
    h = ui.entity_cards_html(stats.group_table(mdf, "map"), "map", stats.side_by_group(rdf, "map"))
    assert "Ascent" in h and "ATK" in h and "low sample" in h


def test_match_label_strips_markdown_specials(match_a):
    mdf, _ = stats.build_frames([match_a], ME)
    r = next(mdf.assign(map="Weird:[map]").itertuples())
    lab = ui.match_label(r)
    assert lab.startswith(":green[**WIN**] 13-1") and "[map]" not in lab and "+21" not in lab


def test_specs_are_json_and_use_validated_colors(mmr_hist):
    for spec in (ui.rr_change_spec(), ui.elo_spec(), ui.trend_spec("acs_rolling", "ACS"), ui.weapon_spec()):
        txt = json.dumps(spec)
        assert spec["background"] == "transparent"
        assert ui.SERIES in txt
    assert ui.NEG in json.dumps(ui.rr_change_spec())
    h = ui.rr_frame(mmr_hist)
    assert list(h["last_change"]) == [21, -18] and list(h["tier"]) == ["Gold 1", "Gold 1"]
    assert ui.rr_frame([]).empty
