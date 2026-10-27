import os
import re
import sqlite3
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path


sqlite3.register_adapter(Decimal, str)
sqlite3.register_adapter(date, date.isoformat)
sqlite3.register_adapter(datetime, lambda value: value.isoformat(sep=' '))
sqlite3.register_adapter(time, time.isoformat)
sqlite3.register_converter('DATE', lambda value: date.fromisoformat(value.decode()))
sqlite3.register_converter('DATETIME', lambda value: datetime.fromisoformat(value.decode()))
sqlite3.register_converter('TIMESTAMP', lambda value: datetime.fromisoformat(value.decode()))
sqlite3.register_converter('TIME', lambda value: time.fromisoformat(value.decode()))


ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = ROOT / 'static' / 'db' / 'schema.sqlite.sql'
DEFAULT_DATABASE_PATH = ROOT / 'instance' / 'tennissel.sqlite3'
DATABASE_SCHEMA_VERSION = '1'


def _matching_parenthesis(value, start):
    quote = None
    depth = 0
    index = start
    while index < len(value):
        char = value[index]
        if quote:
            if char == quote:
                if index + 1 < len(value) and value[index + 1] == quote:
                    index += 1
                else:
                    quote = None
            elif char == '\\' and quote in ("'", '"'):
                index += 1
        elif char in ("'", '"', '`'):
            quote = char
        elif char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise sqlite3.OperationalError('Unbalanced parentheses in SQL statement')


def _split_sql_definitions(value):
    definitions = []
    start = 0
    depth = 0
    quote = None
    index = 0
    while index < len(value):
        char = value[index]
        if quote:
            if char == quote:
                if index + 1 < len(value) and value[index + 1] == quote:
                    index += 1
                else:
                    quote = None
            elif char == '\\' and quote in ("'", '"'):
                index += 1
        elif char in ("'", '"', '`'):
            quote = char
        elif char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        elif char == ',' and depth == 0:
            definitions.append(value[start:index].strip())
            start = index + 1
        index += 1
    final_definition = value[start:].strip()
    if final_definition:
        definitions.append(final_definition)
    return definitions


def _sqlite_column_definition(definition):
    definition = definition.replace('`', '')
    definition = re.sub(r'\bENUM\s*\([^)]*\)', 'TEXT', definition, flags=re.IGNORECASE)
    definition = re.sub(r'\bUNSIGNED\b', '', definition, flags=re.IGNORECASE)
    definition = re.sub(
        r'\s+ON\s+UPDATE\s+CURRENT_TIMESTAMP(?:\(\))?',
        '',
        definition,
        flags=re.IGNORECASE,
    )
    definition = re.sub(r'\bTINYINT\s*\(\s*1\s*\)', 'INTEGER', definition, flags=re.IGNORECASE)
    definition = re.sub(
        r'\b(?:BIGINT|MEDIUMINT|SMALLINT|TINYINT|INT)\s*\([^)]*\)',
        'INTEGER',
        definition,
        flags=re.IGNORECASE,
    )
    definition = re.sub(
        r'\b(?:BIGINT|MEDIUMINT|SMALLINT|TINYINT|INT)\b',
        'INTEGER',
        definition,
        flags=re.IGNORECASE,
    )
    definition = re.sub(r'\bVARCHAR\s*\([^)]*\)', 'TEXT', definition, flags=re.IGNORECASE)
    definition = re.sub(r'\bCHAR\s*\([^)]*\)', 'TEXT', definition, flags=re.IGNORECASE)
    definition = re.sub(r'\bJSON\b', 'TEXT', definition, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', definition).strip()


def _translate_create_table(statement):
    opening = statement.find('(')
    if opening < 0:
        return statement
    closing = _matching_parenthesis(statement, opening)
    definitions = _split_sql_definitions(statement[opening + 1:closing])
    sqlite_definitions = []
    auto_increment = False

    for definition in definitions:
        normalized = definition.strip().replace('`', '')
        if re.match(r'^UNIQUE\s+(?:KEY|INDEX)\b', normalized, flags=re.IGNORECASE):
            unique_key = re.match(
                r'^UNIQUE\s+(?:KEY|INDEX)\s+\w+\s*\((.*)\)$',
                normalized,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if unique_key:
                sqlite_definitions.append(f'UNIQUE ({unique_key.group(1)})')
            continue
        if re.match(r'^(?:KEY|INDEX)\b', normalized, flags=re.IGNORECASE):
            continue
        if re.match(r'^CONSTRAINT\b', normalized, flags=re.IGNORECASE):
            normalized = re.sub(
                r'^CONSTRAINT\s+\w+\s+',
                '',
                normalized,
                count=1,
                flags=re.IGNORECASE,
            )
        if re.search(r'\bAUTO_INCREMENT\b', normalized, flags=re.IGNORECASE):
            column_name = re.match(r'^(\w+)\s+', normalized).group(1)
            sqlite_definitions.append(f'{column_name} INTEGER PRIMARY KEY AUTOINCREMENT')
            auto_increment = True
            continue
        sqlite_definitions.append(_sqlite_column_definition(normalized))

    if auto_increment:
        sqlite_definitions = [
            definition for definition in sqlite_definitions
            if not re.match(r'^PRIMARY KEY\s*\(', definition, flags=re.IGNORECASE)
        ]
    return (
        statement[:opening + 1]
        + '\n'
        + ',\n'.join(sqlite_definitions)
        + '\n)'
    )


def _mysql_on_update_triggers(statement):
    table_match = re.match(
        r'\s*CREATE\s+(?:TEMPORARY\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"]?(\w+)[`"]?\s*\(',
        statement,
        flags=re.IGNORECASE,
    )
    if not table_match:
        return []
    opening = statement.find('(', table_match.start())
    closing = _matching_parenthesis(statement, opening)
    table_name = table_match.group(1)
    triggers = []
    for definition in _split_sql_definitions(statement[opening + 1:closing]):
        if not re.search(r'\bON\s+UPDATE\s+CURRENT_TIMESTAMP', definition, flags=re.IGNORECASE):
            continue
        column_match = re.match(r'\s*[`"]?(\w+)[`"]?', definition)
        if not column_match:
            continue
        column_name = column_match.group(1)
        trigger_name = f'tennissel_update_{table_name}_{column_name}'
        triggers.append(
            f'''
            CREATE TRIGGER IF NOT EXISTS "{trigger_name}"
            AFTER UPDATE ON "{table_name}"
            FOR EACH ROW
            WHEN NEW."{column_name}" IS OLD."{column_name}"
            BEGIN
                UPDATE "{table_name}"
                SET "{column_name}" = CURRENT_TIMESTAMP
                WHERE rowid = NEW.rowid;
            END
            '''
        )
    return triggers


def _translate_sql(statement, parameters, connection):
    column_check = re.search(
        r'FROM\s+INFORMATION_SCHEMA\.COLUMNS.*?TABLE_NAME\s*=\s*[\'"](\w+)[\'"]'
        r'.*?COLUMN_NAME\s*=\s*(%s|[\'"](\w+)[\'"])',
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if column_check:
        column_name = parameters[0] if column_check.group(2) == '%s' else column_check.group(3)
        return (
            'SELECT COUNT(*) FROM pragma_table_info(?) WHERE name = ?',
            (column_check.group(1), column_name),
        )

    index_check = re.search(
        r'FROM\s+INFORMATION_SCHEMA\.STATISTICS.*?TABLE_NAME\s*=\s*[\'"](\w+)[\'"]'
        r'.*?INDEX_NAME\s*=\s*[\'"](\w+)[\'"]',
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if index_check:
        return (
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND name = ?",
            (index_check.group(1), index_check.group(2)),
        )

    for_update = bool(re.search(r'\bFOR\s+UPDATE\b', statement, flags=re.IGNORECASE))
    statement = re.sub(r'\s+FOR\s+UPDATE\b', '', statement, flags=re.IGNORECASE)
    statement = statement.replace('%s', '?')
    statement = re.sub(r'\bINSERT\s+IGNORE\s+INTO\b', 'INSERT OR IGNORE INTO', statement, flags=re.IGNORECASE)
    statement = re.sub(
        r'\bON\s+DUPLICATE\s+KEY\s+UPDATE\b',
        'ON CONFLICT DO UPDATE SET',
        statement,
        flags=re.IGNORECASE,
    )
    statement = re.sub(
        r'\bVALUES\s*\(\s*([A-Za-z_]\w*)\s*\)',
        r'excluded.\1',
        statement,
        flags=re.IGNORECASE,
    )
    statement = re.sub(
        r"DATE_ADD\s*\(\s*CURRENT_TIMESTAMP(?:\(\))?\s*,\s*INTERVAL\s+([+-]?\d+)\s+(DAY|HOUR|MINUTE|SECOND)\s*\)",
        lambda match: (
            f"datetime('now', '{int(match.group(1)):+d} "
            f"{match.group(2).lower()}s')"
        ),
        statement,
        flags=re.IGNORECASE,
    )
    statement = re.sub(r'\bNOW\s*\(\s*\)', 'CURRENT_TIMESTAMP', statement, flags=re.IGNORECASE)
    statement = re.sub(r'\bCURDATE\s*\(\s*\)', "date('now')", statement, flags=re.IGNORECASE)
    statement = re.sub(
        r'\bADDTIME\s*\(\s*([^,()]+)\s*,\s*\'(\d{2}):(\d{2}):(\d{2})\'\s*\)',
        lambda match: (
            f"time({match.group(1).strip()}, '+{int(match.group(2))} hours', "
            f"'+{int(match.group(3))} minutes', '+{int(match.group(4))} seconds')"
        ),
        statement,
        flags=re.IGNORECASE,
    )
    statement = re.sub(r'\bCAST\s*\((.*?)\s+AS\s+CHAR\s*\)', r'CAST(\1 AS TEXT)', statement, flags=re.IGNORECASE | re.DOTALL)
    statement = re.sub(r'\bIF\s*\(', 'IIF(', statement, flags=re.IGNORECASE)
    statement = re.sub(
        r'\bRAND\s*\(\s*\)',
        '(abs(random()) / 9223372036854775808.0)',
        statement,
        flags=re.IGNORECASE,
    )
    statement = re.sub(
        r"GROUP_CONCAT\s*\(\s*(.*?)\s+ORDER\s+BY\s+.*?\s+SEPARATOR\s+'([^']*)'\s*\)",
        lambda match: f"GROUP_CONCAT({match.group(1).strip()}, '{match.group(2)}')",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    statement = re.sub(
        r'ALTER\s+TABLE\s+(\w+)\s+ADD\s+UNIQUE\s+(?:KEY|INDEX)\s+(\w+)\s*\(([^)]*)\)',
        r'CREATE UNIQUE INDEX IF NOT EXISTS \2 ON \1 (\3)',
        statement,
        flags=re.IGNORECASE,
    )
    statement = re.sub(
        r'\s+AFTER\s+\w+',
        '',
        statement,
        flags=re.IGNORECASE,
    )
    if re.match(r'\s*CREATE\s+(?:TEMPORARY\s+)?TABLE\b', statement, flags=re.IGNORECASE):
        statement = _translate_create_table(statement)

    if for_update and not connection.in_transaction:
        connection.execute('BEGIN IMMEDIATE')
    return statement, parameters


class SQLiteCursor:
    def __init__(self, cursor, connection, dictionary=False):
        self._cursor = cursor
        self._connection = connection
        self._dictionary = dictionary

    def execute(self, statement, parameters=()):
        triggers = _mysql_on_update_triggers(statement)
        statement, parameters = _translate_sql(statement, parameters, self._connection)
        self._cursor.execute(statement, parameters)
        for trigger in triggers:
            self._cursor.execute(trigger)
        return self

    def executemany(self, statement, parameters):
        statement, _ = _translate_sql(statement, (), self._connection)
        self._cursor.executemany(statement, parameters)
        return self

    def _convert_row(self, row):
        if self._dictionary and row is not None:
            return dict(row)
        return row

    def fetchone(self):
        return self._convert_row(self._cursor.fetchone())

    def fetchall(self):
        return [self._convert_row(row) for row in self._cursor.fetchall()]

    def fetchmany(self, size=None):
        rows = self._cursor.fetchmany(size) if size is not None else self._cursor.fetchmany()
        return [self._convert_row(row) for row in rows]

    def close(self):
        self._cursor.close()

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class SQLiteConnection(sqlite3.Connection):
    def cursor(self, dictionary=False):
        return SQLiteCursor(super().cursor(), self, dictionary=dictionary)


def _concat(*values):
    if any(value is None for value in values):
        return None
    return ''.join(str(value) for value in values)


def _left_pad(value, width, padding):
    if value is None or padding is None:
        return None
    value = str(value)
    padding = str(padding)
    width = int(width)
    if len(value) >= width or not padding:
        return value[:width]
    needed = width - len(value)
    repeats = (needed + len(padding) - 1) // len(padding)
    return (padding * repeats)[:needed] + value


def _time_format(value, format_string):
    if value is None or format_string is None:
        return None
    try:
        from datetime import datetime, time

        text = str(value)
        parsed = datetime.fromisoformat(text) if ' ' in text else time.fromisoformat(text)
        return parsed.strftime(str(format_string).replace('%i', '%M'))
    except ValueError:
        return None


def get_db_connection():
    database_path = Path(os.environ.get('DATABASE_PATH', DEFAULT_DATABASE_PATH)).expanduser()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        str(database_path),
        timeout=30,
        detect_types=sqlite3.PARSE_DECLTYPES,
        factory=SQLiteConnection,
    )
    connection.row_factory = sqlite3.Row
    connection.create_function('CONCAT', -1, _concat)
    connection.create_function('LPAD', 3, _left_pad)
    connection.create_function('TIME_FORMAT', 2, _time_format)
    connection.execute('PRAGMA foreign_keys = ON')
    connection.execute('PRAGMA busy_timeout = 30000')
    connection.execute('PRAGMA journal_mode = WAL')

    has_metadata_table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'tennissel_metadata'"
    ).fetchone()
    schema_version = None
    if has_metadata_table:
        version_row = connection.execute(
            "SELECT value FROM tennissel_metadata WHERE name = 'schema_version'"
        ).fetchone()
        schema_version = version_row[0] if version_row else None
    if schema_version != DATABASE_SCHEMA_VERSION:
        if not SCHEMA_PATH.is_file():
            connection.close()
            raise FileNotFoundError(f'SQLite schema file is missing: {SCHEMA_PATH}')
        try:
            connection.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
            connection.execute(
                'CREATE TABLE IF NOT EXISTS tennissel_metadata '
                '(name TEXT PRIMARY KEY, value TEXT NOT NULL)'
            )
            connection.execute(
                'INSERT INTO tennissel_metadata (name, value) VALUES (?, ?) '
                'ON CONFLICT(name) DO UPDATE SET value = excluded.value',
                ('schema_version', DATABASE_SCHEMA_VERSION),
            )
            connection.commit()
        except sqlite3.Error:
            connection.rollback()
            connection.close()
            raise
    return connection
