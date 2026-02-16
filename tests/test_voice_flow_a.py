import os

from core.app import create_app
from features import voice_flow_a


def test_voice_flow_a_selftests_pass():
    out = voice_flow_a.selftests()
    assert out.ok is True


def test_voice_flow_a_route_off_by_default():
    prev = os.getenv("VOZ_FEATURE_VOICE_FLOW_A")
    try:
        os.environ.pop("VOZ_FEATURE_VOICE_FLOW_A", None)
        app = create_app()
        paths = {r.path for r in app.routes}
        assert "/twilio/stream" not in paths
    finally:
        if prev is None:
            os.environ.pop("VOZ_FEATURE_VOICE_FLOW_A", None)
        else:
            os.environ["VOZ_FEATURE_VOICE_FLOW_A"] = prev
