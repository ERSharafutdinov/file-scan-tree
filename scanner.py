"""
FileScanTree — многопоточный анализатор файловой системы.

Модуль предоставляет класс FileScanner для обхода файловой системы,
построения иерархического дерева каталогов, поиска дубликатов по MD5
и экспорта результатов в Excel.

Пример:
    >>> from scanner import FileScanner, write_to_excel
    >>> scanner = FileScanner(r'C:\\Users', max_depth=10, compute_md5=True)
    >>> tree, stats, drive, duplicates = scanner.scan()
    >>> write_to_excel('output.xlsx', tree, stats, duplicates)
"""

import datetime
import hashlib
import logging
import os
import time
from collections import Counter
from threading import Lock, Thread
from typing import Any, Dict, List, Set, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


class FileScanner:
    """
    Многопоточный сканер файловой системы.

    Обходит дерево каталогов, начиная с main_path, собирает информацию
    о каждом файле (путь, размер, MD5) и строит иерархическое дерево
    с агрегированными метриками для каждой папки.

    Attributes:
        main_path: Корневой путь для сканирования.
        max_depth: Максимальная глубина рекурсии (влияет на число потоков).
        compute_md5: Вычислять ли MD5-хеши (нужно для поиска дубликатов).
        files: Плоский список файлов [(путь, размер, md5), ...].
        total_size: Суммарный размер всех файлов в байтах.
        active_threads: Словарь активных потоков {номер: путь}.
        thread_counter: Счётчик созданных потоков.
        stats: История статистики сканирования.
        lock: Мьютекс для потокобезопасного доступа к общим структурам.
    """

    def __init__(
        self,
        main_path: str,
        max_depth: int = 10,
        compute_md5: bool = False,
    ) -> None:
        """
        Инициализация сканера.

        Args:
            main_path: Корневой путь для сканирования.
            max_depth: Максимальная глубина рекурсии.
            compute_md5: Вычислять ли MD5-хеши файлов.
        """
        self.main_path = main_path
        self.max_depth = max_depth
        self.compute_md5 = compute_md5

        # Общие структуры для многопоточного сканирования
        self.files: List[Tuple[str, int, str]] = []
        self.total_size: int = 0
        self.active_threads: Dict[int, str] = {}
        self.thread_counter: int = 0
        self.stats: List[Tuple[datetime.datetime, int, int, int, float]] = []
        self.lock = Lock()

    # ------------------------------------------------------------------ #
    #                        Вспомогательные методы                      #
    # ------------------------------------------------------------------ #

    def _md5(self, fname: str, f_size_gb: float) -> str:
        """
        Вычисляет MD5-хеш файла.

        Для файлов > 1 ГБ хеш не вычисляется — возвращается путь к файлу.
        Это экономит ресурсы при сканировании медиа-архивов.

        Args:
            fname: Путь к файлу.
            f_size_gb: Размер файла в гигабайтах.

        Returns:
            MD5-хеш в hex-формате, путь к файлу (для больших) или "1"
            (если вычисление отключено).
        """
        if not self.compute_md5:
            return "1"
        if f_size_gb > 1:
            return fname

        try:
            hash_md5 = hashlib.md5()
            with open(fname, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except (PermissionError, OSError) as e:
            logger.debug("Не удалось вычислить MD5 для %s: %s", fname, e)
            return "error"

    def _process_file(self, file_path: str) -> None:
        """
        Обрабатывает отдельный файл: получает размер, вычисляет MD5
        и добавляет запись в общий список под Lock.

        Args:
            file_path: Полный путь к файлу.
        """
        try:
            size = os.path.getsize(file_path)
            size_gb = size / (2 ** 30)
            digest = self._md5(file_path, size_gb)
            with self.lock:
                self.total_size += size
                self.files.append((file_path, size, digest))
        except (PermissionError, OSError) as e:
            logger.debug("Пропущен файл %s: %s", file_path, e)

    # ------------------------------------------------------------------ #
    #                        Многопоточный обход                         #
    # ------------------------------------------------------------------ #

    def _get_list_fold(self, fn: str, dep: int, c_num: int) -> None:
        """
        Рекурсивно обходит файловую систему, создавая поток на каждую
        подпапку до достижения max_depth.

        Args:
            fn: Путь к текущей директории или файлу.
            dep: Текущая глубина рекурсии.
            c_num: Номер потока (0 для основного и синхронных вызовов).
        """
        if os.path.isdir(fn):
            try:
                for entry in os.listdir(fn):
                    full_path = os.path.join(fn, entry)

                    if os.path.isdir(full_path):
                        if dep < self.max_depth:
                            # Создаём поток для подкаталога
                            with self.lock:
                                self.thread_counter += 1
                                self.active_threads[self.thread_counter] = full_path
                                thread_id = self.thread_counter
                            Thread(
                                target=self._get_list_fold,
                                args=(full_path, dep + 1, thread_id),
                                daemon=False,
                            ).start()
                        else:
                            # Превышена глубина — обходим синхронно
                            self._get_list_fold(full_path, dep + 1, 0)
                    else:
                        self._process_file(full_path)
            except (PermissionError, OSError) as e:
                logger.debug("Пропущена папка %s: %s", fn, e)
        else:
            # Крайний случай: передан путь к файлу
            self._process_file(fn)

        # Удаляем запись о завершённом потоке
        if c_num:
            with self.lock:
                if c_num in self.active_threads:
                    del self.active_threads[c_num]

    def _wait_for_threads(self) -> None:
        """
        Ожидает завершения всех активных потоков, периодически
        записывая статистику в self.stats.
        """
        last_count = -1
        check_interval = 10

        while True:
            with self.lock:
                active = len(self.active_threads)
                if active == 0:
                    break
                snapshot = (
                    datetime.datetime.today(),
                    active,
                    self.thread_counter,
                    len(self.files),
                    round(self.total_size / (2 ** 30), 3),
                )

            if active != last_count:
                logger.info(
                    "Активных потоков: %d из %d, файлов: %d, размер: %.3f ГБ",
                    active,
                    self.thread_counter,
                    len(self.files),
                    self.total_size / (2 ** 30),
                )
                self.stats.append(snapshot)

                if active < 4:
                    check_interval = 1
                    with self.lock:
                        for path in self.active_threads.values():
                            logger.debug("Поток: %s", path)

                last_count = active

            time.sleep(check_interval)

        # Финальная запись
        self.stats.append((
            datetime.datetime.today(),
            0,
            self.thread_counter,
            len(self.files),
            round(self.total_size / (2 ** 30), 3),
        ))

    # ------------------------------------------------------------------ #
    #                       Агрегация и дерево                           #
    # ------------------------------------------------------------------ #

    def get_file_size(self, folder_path: str) -> Tuple[int, float]:
        """
        Возвращает количество файлов и суммарный размер в заданной папке.

        Args:
            folder_path: Путь к папке.

        Returns:
            Кортеж (количество файлов, размер в ГБ).
        """
        count = 0
        size = 0
        normalized = (
            folder_path if folder_path.endswith(os.sep) else folder_path + os.sep
        )

        for file_path, file_size, _ in self.files:
            if normalized in file_path:
                count += 1
                size += file_size

        return count, round(size / (2 ** 30), 3)

    def get_one_depth(
        self, folder_path: str
    ) -> Tuple[List[str], List[Tuple[str, int, str]]]:
        """
        Возвращает список подпапок и файлов, находящихся непосредственно
        в указанной папке (без рекурсии).

        Args:
            folder_path: Путь к папке.

        Returns:
            Кортеж (список подпапок, список файлов [(имя, размер, md5)]).
        """
        subfolders: List[str] = []
        files: List[Tuple[str, int, str]] = []
        normalized = (
            folder_path if folder_path.endswith(os.sep) else folder_path + os.sep
        )

        for file_path, file_size, digest in self.files:
            if normalized not in file_path:
                continue

            rel_parts = file_path.replace(normalized, "").split(os.sep)
            if rel_parts and rel_parts[0].strip() == "":
                del rel_parts[0]

            if len(rel_parts) > 1:
                if rel_parts[0] not in subfolders:
                    subfolders.append(rel_parts[0])
            elif rel_parts:
                files.append((rel_parts[0], file_size, digest))

        return subfolders, files

    def build_tree(
        self,
        file_list: List[Tuple[str, int, str]],
        depth: int,
        max_depth: int,
        path: str,
    ) -> List[Tuple[str, str, float, Any, int, str, str]]:
        """
        Рекурсивно строит иерархическое дерево папок и файлов.

        Args:
            file_list: Плоский список файлов [(путь, размер, md5)].
            depth: Текущая глубина.
            max_depth: Максимальная глубина рекурсии.
            path: Путь к текущей папке.

        Returns:
            Список кортежей:
            (путь, относительный_путь, размер_ГБ, кол-во_файлов_или_дата,
             уровень, тип, md5).
        """
        result: List[Tuple[str, str, float, Any, int, str, str]] = []

        count, size = self.get_file_size(path)

        # Запись для текущей папки
        rel_path = path.replace(self.main_path, "") if self.main_path != path else path
        result.append((path, rel_path, size, count, depth - 1, "fold", "0"))

        subfolders, files = self.get_one_depth(path)

        if depth < max_depth:
            # Обработка файлов текущей папки
            for file_name, file_size, digest in files:
                full_path = os.path.join(path, file_name)
                _, extension = os.path.splitext(file_name)
                try:
                    mod_date = datetime.datetime.fromtimestamp(
                        os.path.getmtime(full_path)
                    )
                    result.append((
                        path,
                        file_name,
                        file_size / (2 ** 30),
                        mod_date,
                        depth,
                        extension,
                        digest,
                    ))
                except FileNotFoundError:
                    logger.warning("Файл удалён во время сканирования: %s", full_path)

            # Рекурсивная обработка подпапок
            for subfolder in sorted(subfolders):
                subfolder_path = os.path.join(path, subfolder)
                if os.path.isdir(subfolder_path):
                    filtered = [f for f in file_list if subfolder_path in f[0]]
                    result += self.build_tree(
                        filtered, depth + 1, max_depth, subfolder_path
                    )

        return result

    # ------------------------------------------------------------------ #
    #                       Поиск дубликатов                             #
    # ------------------------------------------------------------------ #

    def find_duplicates(
        self, tree: List[Tuple[str, str, float, Any, int, str, str]]
    ) -> List[Tuple[str, str, int]]:
        """
        Находит дубликаты файлов по MD5-хешу.

        Args:
            tree: Дерево, полученное из build_tree().

        Returns:
            Список кортежей (md5, пути_через_\\n, количество_копий).
        """
        logger.info("Поиск дубликатов...")

        md5_to_paths: Dict[str, List[str]] = {}
        for record in tree:
            if record[5] != "fold":
                digest = record[6]
                if digest in ("1", "error"):
                    continue
                full_path = os.path.join(record[0], record[1])
                md5_to_paths.setdefault(digest, []).append(full_path)

        # Быстрая проверка: какие хеши встречаются более одного раза
        counter = Counter(digest for digest in md5_to_paths)
        duplicate_hashes = {h for h, n in counter.items() if n > 1}

        duplicates: List[Tuple[str, str, int]] = []
        for digest in duplicate_hashes:
            paths = md5_to_paths[digest]
            duplicates.append((digest, "\n".join(paths), len(paths)))

        logger.info("Найдено групп дубликатов: %d", len(duplicates))
        return duplicates

    # ------------------------------------------------------------------ #
    #                          Основной метод                            #
    # ------------------------------------------------------------------ #

    def scan(
        self,
    ) -> Tuple[
        List[Tuple[str, str, float, Any, int, str, str]],
        List[Tuple[datetime.datetime, int, int, int, float]],
        str,
        List[Tuple[str, str, int]],
    ]:
        """
        Запускает полный цикл сканирования.

        Returns:
            Кортеж (tree, stats, drive_letter, duplicates):
            - tree: иерархическое дерево папок и файлов;
            - stats: временные ряды статистики сканирования;
            - drive_letter: буква диска / имя корневой папки;
            - duplicates: список найденных дубликатов.
        """
        logger.info("Начало сканирования: %s", self.main_path)
        start_time = datetime.datetime.today()
        self.stats.append((start_time, 0, 0, 0, 0))

        # Многопоточный обход
        self._get_list_fold(self.main_path, 0, 0)
        self._wait_for_threads()

        total_gb = round(self.total_size / (2 ** 30), 3)
        elapsed = datetime.datetime.today() - start_time
        logger.info(
            "Сканирование завершено за %s. Файлов: %d, размер: %.3f ГБ",
            elapsed,
            len(self.files),
            total_gb,
        )

        # Построение дерева
        tree = self.build_tree(self.files, 1, self.max_depth, self.main_path)

        # Поиск дубликатов
        duplicates = self.find_duplicates(tree) if self.compute_md5 else []

        # Имя диска / корневой папки
        parts = [p for p in self.main_path.split(os.sep) if p.strip()]
        drive = parts[0].replace(":", "") if parts else "root"

        return tree, self.stats, drive, duplicates


# ---------------------------------------------------------------------- #
#                          Экспорт в Excel                               #
# ---------------------------------------------------------------------- #


def write_to_excel(
    output_path: str,
    tree: List[Tuple],
    stats: List[Tuple],
    duplicates: List[Tuple],
) -> None:
    """
    Сохраняет результаты сканирования в Excel-файл.

    Создаёт три листа:
        - tree: иерархия папок и файлов с группировкой по уровням;
        - stat: статистика сканирования;
        - Дубли: группы идентичных файлов по MD5 (если есть).

    Args:
        output_path: Путь к выходному .xlsx-файлу.
        tree: Дерево, полученное из FileScanner.scan().
        stats: Статистика, полученная из FileScanner.scan().
        duplicates: Список дубликатов, полученный из FileScanner.scan().
    """
    logger.info("Сохранение результатов в %s", output_path)

    # Ограничение для старых версий Excel
    max_rows = 1_048_000
    if len(tree) > max_rows:
        logger.warning("Слишком много строк (%d), усечение до %d", len(tree), max_rows)
        tree = tree[:max_rows]

    with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
        # --- Лист tree ---
        df_tree = pd.DataFrame(
            tree,
            columns=[
                "Путь",
                "Папка",
                "Размер, Гб",
                "кол-во файлов",
                "Уровень",
                "Расширение",
                "md5",
            ],
        )
        df_tree.to_excel(writer, sheet_name="tree", freeze_panes=(1, 2))
        ws_tree = writer.sheets["tree"]
        ws_tree.autofilter("A1:G1")

        number_format = writer.book.add_format({"num_format": "#,##0.00"})
        number_format.set_center_across()
        int_format = writer.book.add_format({"num_format": "#,##0"})
        int_format.set_center_across()

        ws_tree.set_column("A:A", 15)
        ws_tree.set_column("B:B", 65)
        ws_tree.set_column("C:C", 25, number_format)
        ws_tree.set_column("D:E", 25, int_format)
        ws_tree.set_column("F:F", 25)

        # Группировка строк по уровням вложенности
        for i, record in enumerate(tree):
            level = record[4]
            ws_tree.set_row(
                i + 1,
                None,
                None,
                {"hidden": level > 1, "level": level, "collapsed": level > 1},
            )

        # --- Лист stat ---
        df_stat = pd.DataFrame(
            stats,
            columns=[
                "Время",
                "Потоков в работе",
                "Потоков всего",
                "файлов",
                "Размер, Гб",
            ],
        )
        df_stat.to_excel(writer, sheet_name="stat", freeze_panes=(1, 2))
        ws_stat = writer.sheets["stat"]
        ws_stat.set_column("A:E", 25)

        # --- Лист Дубли ---
        if duplicates:
            df_dup = pd.DataFrame(
                duplicates,
                columns=["md5", "файлы", "кол-во файлов"],
            )
            df_dup.to_excel(writer, sheet_name="Дубли", freeze_panes=(1, 2))
            ws_dup = writer.sheets["Дубли"]
            ws_dup.autofilter("A1:C1")
            ws_dup.set_column("A:C", 25)


# ---------------------------------------------------------------------- #
#                        Утилиты файловой системы                        #
# ---------------------------------------------------------------------- #


def delete_empty_folders(root: str) -> Set[str]:
    """
    Удаляет все пустые папки, начиная с нижнего уровня.

    Args:
        root: Корневой путь для очистки.

    Returns:
        Множество удалённых папок.
    """
    deleted: Set[str] = set()

    for current_dir, subdirs, files in os.walk(root, topdown=False):
        still_has_dirs = any(
            os.path.join(current_dir, subdir) not in deleted for subdir in subdirs
        )

        if not files and not still_has_dirs:
            try:
                os.rmdir(current_dir)
                deleted.add(current_dir)
                logger.debug("Удалена пустая папка: %s", current_dir)
            except OSError as e:
                logger.warning("Не удалось удалить папку %s: %s", current_dir, e)

    return deleted


# ---------------------------------------------------------------------- #
#                            Точка входа                                 #
# ---------------------------------------------------------------------- #


def main() -> None:
    """Точка входа для CLI-скрипта file-scan-tree."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s — %(levelname)s — %(message)s",
    )

    start_time = datetime.datetime.today()

    scan_path = input("Введите путь для сканирования (Enter — C:\\): ").strip()
    scan_path = scan_path or "C:\\"

    compute_md5_input = input("Искать дубликаты по MD5? (y/N): ").strip().lower()
    compute_md5 = compute_md5_input in ("y", "yes", "д", "да")

    scanner = FileScanner(scan_path, max_depth=10, compute_md5=compute_md5)
    tree, stats, drive, duplicates = scanner.scan()

    timestamp = (
        datetime.datetime.today()
        .isoformat(sep="_", timespec="minutes")
        .replace(":", "_")
    )
    output_file = f"{timestamp}_tree_{drive}.xlsx"

    write_to_excel(output_file, tree, stats, duplicates)

    total_time = datetime.datetime.today() - start_time
    logger.info("Готово! Файл: %s. Общее время: %s", output_file, total_time)


if __name__ == "__main__":
    main()