from main import release_lock, save_report, try_acquire_lock


def test_lock_roundtrip(tmp_path):
    p = tmp_path / "lock.txt"
    assert try_acquire_lock(path=p) is True
    assert try_acquire_lock(path=p) is False  # 同日已锁
    release_lock(path=p)
    assert try_acquire_lock(path=p) is True


def test_save_report(tmp_path):
    url = save_report("<html></html>", "2026-08-27", tmp_path, "https://ex.com/reports")
    assert url == "https://ex.com/reports/2026-08-27.html"
    assert (tmp_path / "2026-08-27.html").exists()
