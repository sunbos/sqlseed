"""Media modes for the ``bytes`` generator (Navicat 图像或二进制 parity).

Navicat's 图像或二进制 type has two modes — an image generator
(width/height/format) and "pick a random file from a folder" (path +
extension filter). ``_gen_bytes`` grows optional params for both while
keeping the legacy ``length``-only random-bytes behavior untouched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sqlseed.generators.base_provider import BaseProvider

if TYPE_CHECKING:
    # Path 只出现在注解里（from __future__ import annotations 使其延迟求值），
    # 运行时不需要真实导入。
    from pathlib import Path

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _png_dimensions(data: bytes) -> tuple[int, int]:
    """Parse width/height from the IHDR chunk of a PNG byte string."""
    assert data[:8] == PNG_MAGIC
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height


class TestBytesImageMode:
    def test_default_stays_random_bytes(self) -> None:
        data = BaseProvider()._gen_bytes()
        assert isinstance(data, bytes)
        assert len(data) == 16
        assert not data.startswith(PNG_MAGIC)

    def test_width_height_produce_valid_png(self) -> None:
        data = BaseProvider()._gen_bytes(width=320, height=240)
        assert _png_dimensions(data) == (320, 240)

    def test_image_format_png_explicit(self) -> None:
        data = BaseProvider()._gen_bytes(width=2, height=3, image_format="png")
        assert _png_dimensions(data) == (2, 3)

    def test_dimension_defaults_fill_from_the_other_axis(self) -> None:
        assert _png_dimensions(BaseProvider()._gen_bytes(width=5)) == (5, 5)
        assert _png_dimensions(BaseProvider()._gen_bytes(height=7)) == (7, 7)

    def test_jpeg_without_pillow_falls_back_to_png(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """JPEG needs Pillow (optional dep); without it the bytes are PNG.

        Simulate the no-Pillow environment by breaking the import.
        """
        import builtins

        real_import = builtins.__import__

        def blocked(name: str, *args: object, **kwargs: object) -> object:
            if name == "PIL":
                raise ImportError("simulated: PIL not installed")
            return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(builtins, "__import__", blocked)
        data = BaseProvider()._gen_bytes(width=4, height=4, image_format="jpeg")
        assert _png_dimensions(data) == (4, 4)

    @pytest.mark.skipif(
        not __import__("importlib.util", fromlist=["util"]).find_spec("PIL"),
        reason="Pillow not installed",
    )
    def test_jpeg_with_pillow_produces_jpeg_magic(self) -> None:
        data = BaseProvider()._gen_bytes(width=4, height=4, image_format="jpeg")
        assert data[:2] == b"\xff\xd8"  # JPEG SOI marker


class TestBytesFolderMode:
    @pytest.fixture()
    def media_dir(self, tmp_path: Path) -> Path:
        (tmp_path / "a.png").write_bytes(b"PNGFILE-A")
        (tmp_path / "b.jpg").write_bytes(b"JPGFILE-B")
        (tmp_path / "notes.txt").write_text("not media")
        (tmp_path / "sub").mkdir()
        return tmp_path

    def test_picks_only_files_matching_extensions(self, media_dir: Path) -> None:
        provider = BaseProvider()
        for _ in range(10):
            data = provider._gen_bytes(folder=str(media_dir), extensions=["png", "jpg"])
            assert data in (b"PNGFILE-A", b"JPGFILE-B")

    def test_extension_match_is_case_insensitive_and_dot_tolerant(self, media_dir: Path) -> None:
        provider = BaseProvider()
        for _ in range(10):
            data = provider._gen_bytes(folder=str(media_dir), extensions=[".PNG"])
            assert data == b"PNGFILE-A"

    def test_no_extension_filter_matches_all_files(self, media_dir: Path) -> None:
        provider = BaseProvider()
        data = provider._gen_bytes(folder=str(media_dir))
        assert data.startswith((b"PNGFILE-", b"JPGFILE-", b"not media"))

    def test_missing_folder_raises_config_error(self) -> None:
        """Folder errors are deterministic — ConfigurationError, NOT the
        retriable GenerationError (ValueError gets wrapped into GenerationError
        by the stream layer and pointlessly retried 1000×, hiding the cause)."""
        from sqlseed.generators._protocol import ConfigurationError

        with pytest.raises(ConfigurationError, match="folder"):
            BaseProvider()._gen_bytes(folder="/nonexistent/dir/xyz")

    def test_no_matching_files_raises_config_error(self, media_dir: Path) -> None:
        from sqlseed.generators._protocol import ConfigurationError

        with pytest.raises(ConfigurationError, match="no files"):
            BaseProvider()._gen_bytes(folder=str(media_dir), extensions=["gif"])


class TestBytesMediaProviderPassthrough:
    """faker/mimesis override ``_gen_bytes`` — the media modes must reach
    the BaseProvider helper through their signatures."""

    def test_faker_provider_delegates_media_mode(self) -> None:
        from sqlseed.generators.faker_provider import FakerProvider

        data = FakerProvider()._gen_bytes(width=6, height=2)
        assert _png_dimensions(data) == (6, 2)

    def test_faker_provider_keeps_legacy(self) -> None:
        from sqlseed.generators.faker_provider import FakerProvider

        data = FakerProvider()._gen_bytes(length=8)
        assert isinstance(data, bytes)

    def test_mimesis_provider_delegates_media_mode(self) -> None:
        pytest.importorskip("mimesis")
        from sqlseed.generators.mimesis_provider import MimesisProvider

        data = MimesisProvider()._gen_bytes(width=6, height=2)
        assert _png_dimensions(data) == (6, 2)
