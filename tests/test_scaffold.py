import json
from pathlib import Path

from custom_components.luba import const

ROOT = Path(__file__).parent.parent
PKG = ROOT / "custom_components" / "luba"


def test_manifest():
    m = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))
    assert m["domain"] == "luba"
    assert m["iot_class"] == "calculated"
    assert m["config_flow"] is True
    assert m["single_config_entry"] is True
    assert m["requirements"] == []
    # hassfest: domain, name first, the rest sorted
    keys = list(m)
    assert keys[:2] == ["domain", "name"] and keys[2:] == sorted(keys[2:])


def test_hacs_json():
    h = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert h == {"name": "Luba Scheduler", "homeassistant": "2026.3.0",
                 "hide_default_branch": True}


def test_const_domain():
    assert const.DOMAIN == "luba"


def test_translations_match_strings():
    strings = json.loads((PKG / "strings.json").read_text(encoding="utf-8"))
    en = json.loads((PKG / "translations" / "en.json").read_text(encoding="utf-8"))
    assert strings == en
