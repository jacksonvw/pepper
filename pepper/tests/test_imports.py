"""Smoke imports — every module should import cleanly under offscreen Qt."""


def test_import_main():
    import pepper.main  # noqa: F401


def test_import_config():
    from pepper.core.config import AppConfig, load_config, save_config  # noqa: F401


def test_import_image_view():
    from pepper.ui.image_view import ImageView  # noqa: F401


def test_import_main_window():
    from pepper.ui.main_window import MainWindow  # noqa: F401


def test_import_preferences():
    from pepper.ui.dialogs.preferences import PreferencesDialog  # noqa: F401
