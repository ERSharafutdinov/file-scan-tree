"""Тесты для FileScanner и вспомогательных функций."""

import datetime
import os
import tempfile

import pytest

from scanner import (
    FileScanner,
    delete_empty_folders,
    write_to_excel,
)


@pytest.fixture
def temp_structure():
    """Временная структура: 3 файла, вложенные и пустая папки."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "sub1", "nested"))
        os.makedirs(os.path.join(tmpdir, "empty_folder"))

        with open(os.path.join(tmpdir, "file1.txt"), "w", encoding="utf-8") as f:
            f.write("Hello World")
        with open(os.path.join(tmpdir, "sub1", "file2.txt"), "w", encoding="utf-8") as f:
            f.write("Content 2")
        with open(
            os.path.join(tmpdir, "sub1", "nested", "file3.txt"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("Content 3")

        yield tmpdir


def test_scanner_init(temp_structure):
    """Проверка инициализации сканера."""
    scanner = FileScanner(temp_structure, max_depth=10, compute_md5=False)
    assert scanner.main_path == temp_structure
    assert scanner.max_depth == 10
    assert scanner.compute_md5 is False
    assert scanner.files == []
    assert scanner.total_size == 0


def test_scan_collects_files(temp_structure):
    """Проверка, что сканер собирает все файлы."""
    scanner = FileScanner(temp_structure)
    scanner._get_list_fold(temp_structure, 0, 0)
    scanner._wait_for_threads()
    assert len(scanner.files) == 3


def test_build_tree(temp_structure):
    """Проверка построения дерева каталогов."""
    scanner = FileScanner(temp_structure)
    scanner._get_list_fold(temp_structure, 0, 0)
    scanner._wait_for_threads()
    tree = scanner.build_tree(scanner.files, 1, scanner.max_depth, temp_structure)

    assert any(rec[5] == "fold" and rec[0] == temp_structure for rec in tree)

    files = [rec for rec in tree if rec[5] != "fold"]
    assert len(files) >= 3


def test_find_duplicates(temp_structure):
    """Проверка поиска дубликатов по MD5."""
    with open(os.path.join(temp_structure, "duplicate.txt"), "w", encoding="utf-8") as f:
        f.write("Hello World")

    scanner = FileScanner(temp_structure, compute_md5=True)
    scanner._get_list_fold(temp_structure, 0, 0)
    scanner._wait_for_threads()
    tree = scanner.build_tree(scanner.files, 1, scanner.max_depth, temp_structure)
    duplicates = scanner.find_duplicates(tree)

    assert len(duplicates) >= 1


def test_delete_empty_folders(temp_structure):
    """Проверка удаления пустых папок."""
    empty_path = os.path.join(temp_structure, "empty_folder")
    assert os.path.exists(empty_path)

    deleted = delete_empty_folders(temp_structure)
    assert empty_path in deleted
    assert not os.path.exists(empty_path)


def test_write_to_excel(temp_structure):
    """Проверка экспорта в Excel."""
    scanner = FileScanner(temp_structure, compute_md5=True)
    scanner._get_list_fold(temp_structure, 0, 0)
    scanner._wait_for_threads()
    tree = scanner.build_tree(scanner.files, 1, scanner.max_depth, temp_structure)

    stats = [(datetime.datetime.today(), 1, 2, 3, 0.5)]
    dup = [("md5_hash", "path1\npath2", 2)]

    output_file = os.path.join(temp_structure, "test_output.xlsx")
    write_to_excel(output_file, tree, stats, dup)

    assert os.path.exists(output_file)
    assert os.path.getsize(output_file) > 0


def test_scan_full_cycle(temp_structure):
    """Полный цикл сканирования (интеграционный тест)."""
    scanner = FileScanner(temp_structure, max_depth=10, compute_md5=True)
    tree, stats, drive, duplicates = scanner.scan()

    assert len(tree) > 0
    assert len(stats) > 0
    assert isinstance(drive, str)
    assert isinstance(duplicates, list)