# Подробное руководство по использованию

## Продвинутые сценарии

### Сканирование конкретной папки

```python
from scanner import FileScanner, write_to_excel

scanner = FileScanner(r'D:\Documents', max_depth=5, compute_md5=True)
tree, stats, drive, duplicates = scanner.scan()
write_to_excel('documents_scan.xlsx', tree, stats, duplicates)
```

### Поиск и ручной анализ дубликатов

```python
scanner = FileScanner(r'C:\Photos', compute_md5=True)
tree, _, _, duplicates = scanner.scan()

for md5, paths, count in duplicates:
    print(f"Найдено {count} копий файла с MD5 {md5}:")
    print(paths)
```

### Работа с ошибками прав доступа

Сканер автоматически пропускает файлы и папки, к которым нет доступа.
Для детального вывода установите уровень логирования:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Обработка больших файлов (> 1 ГБ)

Для файлов размером более 1 ГБ MD5-хеш не вычисляется — вместо него
сохраняется путь к файлу. Это снижает нагрузку на диск при сканировании
медиа-архивов. Порог можно изменить в методе `FileScanner._md5()`.

### Программное удаление пустых папок

```python
from scanner import delete_empty_folders

deleted = delete_empty_folders(r'D:\Downloads')
print(f"Удалено папок: {len(deleted)}")
```

## Оптимизация производительности

1. **Быстрое сканирование** — установите `compute_md5=False`.
2. **Ограничение глубины** — уменьшите `max_depth`.
3. **SSD** — увеличьте лимит потоков (по умолчанию глубина ограничивает число потоков).
4. **Логирование** — на больших объёмах установите `level=logging.WARNING`,
   чтобы не засорять консоль.

## Запуск в Docker (опционально)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -e .
CMD ["file-scan-tree"]
```