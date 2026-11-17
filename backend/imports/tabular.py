import csv
import io
from itertools import islice
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from xml.etree.ElementTree import ParseError

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from .csv_utils import get_csv_dict_reader


MAX_DATA_ROWS = 50000


def _read_rows(reader):
    rows = list(islice(reader, MAX_DATA_ROWS + 1))
    if len(rows) > MAX_DATA_ROWS:
        raise ValueError("Uploads are limited to 50,000 data rows.")
    return rows


def read_tabular(upload, instrument, sheet=None):
    """Return the selected sheet's rows and metadata, or the workbook's sheet names."""
    upload.seek(0)
    try:
        if Path(upload.name).suffix.lower() != ".xlsx":
            if sheet:
                raise ValueError("Sheet selection applies only to Excel workbooks.")
            reader, metadata = get_csv_dict_reader(upload.read().decode("utf-8-sig"), instrument)
            return _read_rows(reader), metadata

        with ZipFile(upload) as archive:
            if sum(entry.file_size for entry in archive.infolist()) > 50 * 1024 * 1024:
                raise ValueError("The expanded Excel workbook exceeds 50 MB.")
        upload.seek(0)
        workbook = load_workbook(upload, read_only=True, data_only=True, keep_links=False)
        try:
            sheets = workbook.sheetnames
            if not sheet and len(sheets) != 1:
                return None, {"sheets": sheets}
            sheet = sheet or sheets[0]
            if sheet not in sheets:
                raise ValueError("The selected sheet is unavailable.")
            worksheet = workbook[sheet]
            if (worksheet.max_row or 0) > 50000 or (worksheet.max_column or 0) > 256:
                raise ValueError("Excel sheets are limited to 50,000 rows and 256 columns.")
            # Use the same header detection and mapping as text uploads.
            buffer = io.StringIO()
            writer = csv.writer(buffer, delimiter=instrument.delimiter)
            for index, cells in enumerate(worksheet.values):
                if index >= 50000 or len(cells) > 256:
                    raise ValueError("Excel sheets are limited to 50,000 rows and 256 columns.")
                if any(cell is not None for cell in cells):
                    writer.writerow(cells)
            reader, metadata = get_csv_dict_reader(buffer.getvalue(), instrument)
            return _read_rows(reader), {**metadata, "sheet": sheet, "sheets": sheets}
        finally:
            workbook.close()
    except (BadZipFile, InvalidFileException, KeyError, IndexError, ParseError) as exc:
        raise ValueError("Unable to read the Excel workbook.") from exc
    finally:
        upload.seek(0)
