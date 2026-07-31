"""Component login profile resolution for Configure / discovery."""

from pathlib import Path

from browser_bot.sites import get_login_profile_path, resolve_login_profile_path


def test_resolve_prefers_component_profile(tmp_path, monkeypatch):
    import browser_bot.sites as sites

    monkeypatch.setattr(sites, "SITES_DIR", tmp_path)
    site = "OpenAI"
    component = "chatgpt"
    component_profile = get_login_profile_path(site, component)
    component_profile.mkdir(parents=True)
    (component_profile / "Default").mkdir()
    site_profile = get_login_profile_path(site)
    site_profile.mkdir(parents=True)

    resolved = resolve_login_profile_path(site, component)
    assert resolved == component_profile
    assert resolved != site_profile


def test_resolve_falls_back_to_site_profile(tmp_path, monkeypatch):
    import browser_bot.sites as sites

    monkeypatch.setattr(sites, "SITES_DIR", tmp_path)
    site = "OpenAI"
    component = "chatgpt"
    site_profile = get_login_profile_path(site)
    site_profile.mkdir(parents=True)

    resolved = resolve_login_profile_path(site, component)
    assert resolved == site_profile
    assert not get_login_profile_path(site, component).exists()


def test_resolve_without_component_is_site_path(tmp_path, monkeypatch):
    import browser_bot.sites as sites

    monkeypatch.setattr(sites, "SITES_DIR", tmp_path)
    site = "OpenAI"
    assert resolve_login_profile_path(site) == get_login_profile_path(site)
    assert isinstance(resolve_login_profile_path(site), Path)
