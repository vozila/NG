from core.app import create_app


def test_create_app_routes():
    app = create_app()
    assert len(app.routes) >= 1
