# 🌳 FileScanTree

**Многопоточный анализатор файловой системы на Python** — обход каталогов, построение иерархического дерева, поиск дубликатов по MD5 и экспорт отчёта в Excel.

[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)]()
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

---

## ✨ Возможности

- ⚡ **Многопоточный обход** — потоки на каждую подпапку, ускорение на больших деревьях
- 📂 **Иерархическое дерево** — папки и файлы с уровнями вложенности, размерами и датами
- 🔍 **Поиск дубликатов** — по MD5-хешу (файлы > 1 ГБ пропускаются для экономии)
- 📊 **Экспорт в Excel** — три листа: `tree`, `stat`, `Дубли` с группировкой и автофильтром
- 🛡️ **Устойчивость к ошибкам** — корректный пропуск файлов с ограниченным доступом
- 🧹 **Утилита очистки** — удаление пустых папок

## 📦 Установка

```bash
git clone https://github.com/ERSharafutdinov/file-scan-tree.git
cd file-scan-tree

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/macOS

pip install -r requirements.txt
```

Для установки в режиме разработки (с линтером и тестами):

```bash
pip install -e ".[dev]"
```

## 🖥️ Использование

### CLI

После установки `pip install -e .` доступна команда:

```bash
file-scan-tree
```

Скрипт спросит путь (Enter — `C:\`) и сохранит `YYYY-MM-DD_HH-MM_tree_<диск>.xlsx`.

### Как библиотека

```python
from scanner import FileScanner, write_to_excel

scanner = FileScanner(r'C:\Users\YourName\Documents', max_depth=10, compute_md5=True)
tree, stats, drive, duplicates = scanner.scan()
write_to_excel('output.xlsx', tree, stats, duplicates)
```

## ⚙️ Параметры `FileScanner`

| Параметр       | Тип   | По умолчанию | Описание                                     |
|----------------|-------|--------------|----------------------------------------------|
| `main_path`    | `str` | —            | Корневой путь сканирования                   |
| `max_depth`    | `int` | `10`         | Максимальная глубина рекурсии                |
| `compute_md5`  | `bool`| `False`      | Вычислять ли MD5 (нужно для поиска дублей)   |

## 📊 Структура Excel-отчёта

| Лист    | Содержимое                                                                 |
|---------|----------------------------------------------------------------------------|
| `tree`  | Путь, папка, размер (ГБ), кол-во файлов, уровень, расширение, md5          |
| `stat`  | Временные метки, активные потоки, всего потоков, файлов, размер            |
| `Дубли` | MD5, список путей (по одному на строку), количество копий                  |

## 🧪 Тестирование

```bash
pip install -e ".[dev]"
pytest
```

## 🗂️ Структура проекта

```
file-scan-tree/
├── scanner.py              # Основной модуль (класс FileScanner)
├── test_scanner.py         # Pytest-тесты
├── usage.md                # Расширенное руководство
├── APPROACH.md             # Методология и математическая модель
├── .github/workflows/ci.yml
├── pyproject.toml
├── requirements.txt
├── LICENSE
├── .gitignore
└── README.md
```

## 🛣️ Roadmap

- [x] Замена глобальных переменных на контекст класса
- [x] Структурированное логирование (`logging` вместо `print`)
- [ ] Кроссплатформенность (сейчас пути заточены под Windows `\`)
- [ ] Инкрементальное сканирование (кэш MD5 между запусками)
- [ ] Экспорт в Parquet / SQLite для больших объёмов
- [ ] Веб-интерфейс (Streamlit) для визуализации дерева

## 🤝 Вклад

Pull-request'ы приветствуются! Открой issue, форкни репозиторий, создай ветку `feature/...` — и вперёд.

## 📄 Лицензия

MIT — см. [LICENSE](LICENSE).

## 📧 Контакты

**Эдуард Шарафутдинов** — [@ERSharafutdinov](https://github.com/ERSharafutdinov)