import pytest
from PIL import Image

import app as app_module


def _write_original(images_dir, name, size=(1000, 1000), mode="RGB"):
    images_dir.mkdir(parents=True, exist_ok=True)
    p = images_dir / name
    Image.new(mode, size, (120, 80, 40) if mode == "RGB" else (10, 20, 30, 255)).save(
        p, "PNG" if name.lower().endswith(".png") else "JPEG"
    )
    return p


def test_deriv_name_is_always_jpeg():
    assert app_module.deriv_name("r123_01.jpeg", "m") == "r123_01_m.jpeg"
    assert app_module.deriv_name("r123_01.png", "s") == "r123_01_s.jpeg"
    assert app_module.deriv_name("m456_01.jpeg", "m") == "m456_01_m.jpeg"


def test_is_original_image_excludes_derivatives(tmp_path):
    assert app_module.is_original_image(tmp_path / "r1_01.jpeg") is True
    assert app_module.is_original_image(tmp_path / "r1_01_m.jpeg") is False
    assert app_module.is_original_image(tmp_path / "r1_01_s.jpeg") is False
    assert app_module.is_original_image(tmp_path / "notes.txt") is False


def test_make_derivatives_creates_sized_siblings(tmp_path):
    orig = _write_original(tmp_path, "r999_01.jpeg", size=(1200, 1200))
    app_module.make_derivatives(orig)

    m = tmp_path / "r999_01_m.jpeg"
    s = tmp_path / "r999_01_s.jpeg"
    assert m.exists() and s.exists()
    assert max(Image.open(m).size) == 400
    assert max(Image.open(s).size) == 150
    # derivatives are meaningfully smaller than the original
    assert s.stat().st_size < orig.stat().st_size


def test_make_derivatives_handles_non_jpeg_source(tmp_path):
    orig = _write_original(tmp_path, "r888_01.png", size=(800, 600), mode="RGBA")
    app_module.make_derivatives(orig)
    m = tmp_path / "r888_01_m.jpeg"
    assert m.exists()
    assert Image.open(m).mode == "RGB"


def test_make_derivatives_is_idempotent(tmp_path):
    orig = _write_original(tmp_path, "r777_01.jpeg")
    app_module.make_derivatives(orig)
    mtime = (tmp_path / "r777_01_m.jpeg").stat().st_mtime_ns
    app_module.make_derivatives(orig)
    assert (tmp_path / "r777_01_m.jpeg").stat().st_mtime_ns == mtime


def test_backfill_skips_derivatives_and_counts_originals(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "IMAGES_DIR", tmp_path)
    _write_original(tmp_path, "r1_01.jpeg")
    _write_original(tmp_path, "r2_01.jpeg")
    n = app_module.backfill_derivatives()
    assert n == 2
    assert sorted(p.name for p in tmp_path.glob("*_m.jpeg")) == ["r1_01_m.jpeg", "r2_01_m.jpeg"]


async def test_manifest_lists_only_derivatives(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "IMAGES_DIR", tmp_path)
    orig = _write_original(tmp_path, "r55_01.jpeg")
    app_module.make_derivatives(orig)

    r = await client.get("/api/images/manifest")
    assert r.status_code == 200
    assert sorted(r.json()) == ["r55_01_m.jpeg", "r55_01_s.jpeg"]


async def test_regenerate_thumbnails_endpoint(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "IMAGES_DIR", tmp_path)
    _write_original(tmp_path, "r66_01.jpeg")

    r = await client.post("/api/admin/regenerate-thumbnails")
    assert r.status_code == 200
    assert r.json() == {"processed": 1}
    assert (tmp_path / "r66_01_s.jpeg").exists()


async def test_download_all_images_generates_derivatives(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "IMAGES_DIR", tmp_path)

    class _Resp:
        status_code = 200

        def __init__(self):
            buf = tmp_path / "_src.jpeg"
            Image.new("RGB", (900, 900), (1, 2, 3)).save(buf, "JPEG")
            self.content = buf.read_bytes()

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            return _Resp()

    monkeypatch.setattr(app_module.httpx, "AsyncClient", lambda *a, **k: _Client())

    out = await app_module.download_all_images(
        [{"uri": "https://img/r1.jpeg"}], "r12345", {}
    )
    assert out == [{"filename": "r12345_01.jpeg", "seq": 1}]
    assert (tmp_path / "r12345_01_m.jpeg").exists()
    assert (tmp_path / "r12345_01_s.jpeg").exists()
