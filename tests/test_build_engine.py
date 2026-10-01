import pytest

from tools.build_engine import check_mlx, fix_mlx


def write(path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def symlink(link, target):
    try:
        link.symlink_to(target)
    except OSError:  # Windows không có quyền symlink
        pytest.skip("symlinks are not available")


def frozen(tmp_path, *, links=True, metallib=True):
    """Bố cục PyInstaller cho mlx: file thật trong mlx/lib, symlink ở thư mục gốc."""
    root = tmp_path / "_internal"
    write(root / "mlx/lib/libmlx.dylib", b"mlx")
    write(root / "mlx/lib/libjaccl.dylib", b"jaccl")
    if metallib:
        write(root / "mlx/lib/mlx.metallib", b"metal")
    write(root / "mlx/core.cpython-312-darwin.so")
    if links:
        symlink(root / "libmlx.dylib", "mlx/lib/libmlx.dylib")
        symlink(root / "libjaccl.dylib", "mlx/lib/libjaccl.dylib")
    return tmp_path, root


def test_check_fails_on_the_v0_7_10_layout(tmp_path):
    # Tauri chép symlink thành file thật: libmlx.dylib ở _internal/ và mlx/lib/, mlx.metallib chỉ ở mlx/lib/
    root = tmp_path / "_internal"
    for d in (root, root / "mlx/lib"):
        write(d / "libmlx.dylib")
    write(root / "mlx/lib/mlx.metallib")
    with pytest.raises(SystemExit, match="_internal"):
        check_mlx(tmp_path)


def test_fix_puts_the_metallib_next_to_the_loaded_library_once(tmp_path):
    engine, root = frozen(tmp_path)
    fix_mlx(engine)
    check_mlx(engine)
    for name, data in (("libmlx.dylib", b"mlx"), ("libjaccl.dylib", b"jaccl"), ("mlx.metallib", b"metal")):
        assert (root / name).is_file() and not (root / name).is_symlink()
        assert (root / name).read_bytes() == data
        assert not (root / "mlx/lib" / name).exists()  # không chép đôi


def test_fix_keeps_a_second_library_working(tmp_path):
    engine, root = frozen(tmp_path, links=False)
    write(root / "libmlx.dylib", b"mlx")  # bản thật thứ hai, như khi chưa có symlink
    fix_mlx(engine)
    check_mlx(engine)
    assert (root / "mlx.metallib").is_file() and (root / "mlx/lib/mlx.metallib").is_file()


def test_fix_handles_the_layout_without_internal(tmp_path):
    write(tmp_path / "libmlx.dylib")
    write(tmp_path / "mlx/lib/mlx.metallib")
    fix_mlx(tmp_path)
    check_mlx(tmp_path)
    assert (tmp_path / "mlx.metallib").is_file()


def test_fix_fails_when_the_metallib_is_not_collected(tmp_path):
    engine, _ = frozen(tmp_path, metallib=False)
    with pytest.raises(SystemExit, match="mlx.metallib is missing"):
        fix_mlx(engine)


def test_fix_fails_when_mlx_is_not_collected(tmp_path):
    write(tmp_path / "_internal/mlx/lib/mlx.metallib")
    with pytest.raises(SystemExit, match="libmlx.dylib is missing"):
        fix_mlx(tmp_path)
    with pytest.raises(SystemExit, match="no mlx"):
        check_mlx(tmp_path)
