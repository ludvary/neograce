"""
io_formats.py - plain text data files (columns of numbers).

Grace convention: a line with "&" separates blocks (data sets) in one file.
Lines starting with # @ ! % are comments and are skipped.
"""
import re

import numpy as np

from .model import SET_TYPE_COLUMNS

# .agr support lives in agr.py; these names are re-exported for convenience
from .agr import read_agr, write_agr  # noqa: F401

SEPARATORS = re.compile(r"[\s,;]+")      # whitespace, commas or semicolons


def to_number(token):
    """float(token), or NaN if the token is not a number."""
    try:
        return float(token)
    except ValueError:
        return np.nan


def split_line(line):
    """Split a line into tokens on whitespace, commas and semicolons."""
    tokens = []
    for token in SEPARATORS.split(line):
        if token != "":
            tokens.append(token)
    return tokens


def is_all_nan(values):
    for v in values:
        if not np.isnan(v):
            return False
    return True


def rows_to_array(rows):
    """List of rows (lists of numbers, maybe of different length) -> 2D array, padded with NaN."""
    columns = 0
    for row in rows:
        columns = max(columns, len(row))
    array = np.full((len(rows), columns), np.nan)
    for i in range(len(rows)):
        row = rows[i]
        for j in range(len(row)):
            array[i, j] = row[j]
    return array


def read_ascii(path):
    """Read a data file. Returns a list of 2D arrays (rows x columns), one per block."""
    blocks = []
    rows = []
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            text = line.strip()
            if text == "" or text[0] in "#@!%":
                continue
            if text.startswith("&"):
                if len(rows) > 0:
                    blocks.append(rows)
                    rows = []
                continue
            values = []
            for token in split_line(text):
                values.append(to_number(token))
            if len(values) == 0 or is_all_nan(values):
                continue                     # a header or text line
            rows.append(values)
    if len(rows) > 0:
        blocks.append(rows)

    arrays = []
    for block in blocks:
        arrays.append(rows_to_array(block))
    return arrays


def column_names(path):
    """Column names from a header line like "# t  signal  error", if the file has one."""
    last_text_line = []
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            text = line.strip()
            if text == "":
                continue
            tokens = split_line(text.lstrip("#@!% "))
            numbers = []
            for token in tokens:
                numbers.append(to_number(token))
            if len(tokens) > 0 and not is_all_nan(numbers):
                break                         # first data line: stop looking
            last_text_line = tokens
    return last_text_line


def parse_columns(spec):
    """"1:3:4" -> [0, 2, 3]  (1-based in the text, 0-based in the result)."""
    columns = []
    for part in re.split(r"[:,\s]+", spec.strip()):
        if part != "":
            columns.append(int(part) - 1)
    if len(columns) < 2 or min(columns) < 0:
        raise ValueError("Column spec needs at least two 1-based columns, e.g. 1:2 or 1:2:3")
    return columns


def parse_column_list(spec):
    """"1:2 2:3, 1:3:4" -> [[0, 1], [1, 2], [0, 2, 3]]."""
    result = []
    for part in re.split(r"[\s,;]+", spec.strip()):
        if part != "":
            result.append(parse_columns(part))
    if len(result) == 0:
        raise ValueError("Give at least one column spec such as 1:2")
    return result


def error_type_for(column_count):
    """The set type to use for a column spec without an explicit type: x:y, x:y:dy, x:y:dx:dy."""
    if column_count == 3:
        return "xydy"
    if column_count == 4:
        return "xydxdy"
    return "xy"


def blocks_to_sets(blocks, mode="single", set_type="xy", cols=None):
    """Turn blocks of columns into data sets.

    Returns a list of (x, y, set_type, error_columns). Use them like this:
        ds = graph.add_set(x, y)
        ds.set_errors(set_type, error_columns)

    mode "single": one set per block: x, y, then the error columns of set_type
    mode "nxy":    x in column 1, one set (type xy) for every other column
    mode "block":  `cols` is a list of column specs from parse_column_list();
                   columns after x:y are the error columns of set_type
                   (with set_type "xy", x:y:c means xydy and x:y:c:d means xydxdy)
    """
    error_names = SET_TYPE_COLUMNS.get(set_type, [])
    result = []
    for a in blocks:
        rows = a.shape[0]
        columns = a.shape[1]
        if mode == "block":
            specs = cols
            if specs is None:
                specs = [[0, 1]]
            if len(specs) > 0 and isinstance(specs[0], int):
                specs = [specs]               # a single spec like [0, 2]
            for spec in specs:
                if max(spec) >= columns:
                    raise ValueError("Column " + str(max(spec) + 1) + " requested but the file has only "
                                     + str(columns) + " columns")
                this_type = set_type
                if this_type == "xy" and len(spec) > 2:
                    this_type = error_type_for(len(spec))
                errors = []
                for k in range(2, len(spec)):
                    errors.append(a[:, spec[k]].copy())
                result.append((a[:, spec[0]].copy(), a[:, spec[1]].copy(), this_type, errors))
        elif columns == 1:
            result.append((np.arange(rows, dtype=float), a[:, 0].copy(), "xy", []))   # x = 0, 1, 2, ...
        elif mode == "nxy":
            for j in range(1, columns):
                result.append((a[:, 0].copy(), a[:, j].copy(), "xy", []))
        else:
            errors = []
            for k in range(len(error_names)):
                if 2 + k < columns:
                    errors.append(a[:, 2 + k].copy())
            result.append((a[:, 0].copy(), a[:, 1].copy(), set_type, errors))
    return result


def write_ascii(path, sets):
    """Write sets as columns (x, y, then any error columns), separated by "&" lines."""
    with open(path, "w") as fh:
        for k in range(len(sets)):
            ds = sets[k]
            if k > 0:
                fh.write("&\n")
            fh.write("# type " + ds.set_type() + "\n")
            if ds.legend:
                fh.write("# " + ds.legend + "\n")
            columns = ds.columns()
            for i in range(len(ds)):
                words = []
                for column in columns:
                    words.append("%.10g" % column[i])
                fh.write(" ".join(words) + "\n")
