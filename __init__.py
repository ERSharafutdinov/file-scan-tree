"""FileScanTree — многопоточный анализатор файловой системы."""

from scanner import FileScanner, write_to_excel, delete_empty_folders

__version__ = "1.0.0"
__all__ = ["FileScanner", "write_to_excel", "delete_empty_folders"]