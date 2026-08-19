"""
Convert an employee CSV file into a SQLite database.

Usage:
    python csv_to_sqlite.py [input.csv] [output.db]

Examples:
    python csv_to_sqlite.py employees_with_uuids.csv
    python csv_to_sqlite.py employees_with_uuids.csv employees.db

The CSV is expected (but auto-detected) to have these columns:
    uuid, first_name, last_name, email [, counter]

The resulting DB has a table named `employees` with:
    uuid        TEXT NOT NULL PRIMARY KEY
    first_name  TEXT
    last_name   TEXT
    email       TEXT
    counter     INTEGER NOT NULL DEFAULT 0

Behavior:
    - The CSV file must be provided as an argument.
    - If the database does not exist, it will be created.
    - If the database exists, the `employees` table will be deleted
      and recreated before importing the CSV data.
    - The database file itself is NOT deleted.

Uses only the Python standard library.
"""

import csv
import os
import sqlite3
import sys


DEFAULT_OUTPUT = "employees.db"
TABLE_NAME = "employees"


def print_usage():
    """Print the script usage instructions."""
    print()
    print("Usage:")
    print("  python csv_to_sqlite.py [input.csv] [output.db]")
    print()
    print("Examples:")
    print("  python csv_to_sqlite.py employees_with_uuids.csv")
    print("  python csv_to_sqlite.py employees_with_uuids.csv employees.db")
    print()


def build_table_schema(fieldnames):
    """Build the CREATE TABLE statement based on CSV headers."""

    type_map = {
        "uuid": "TEXT NOT NULL",
        "uuid4": "TEXT NOT NULL",
        "counter": "INTEGER NOT NULL DEFAULT 0",
        "first_name": "TEXT",
        "last_name": "TEXT",
        "email": "TEXT",
    }

    columns = []
    primary_key_colname = None

    for name in fieldnames:
        col = (name or "").strip()

        if not col:
            continue

        if col.lower() in ("uuid", "uuid4"):
            primary_key_colname = col
            columns.append(f'"{col}" TEXT NOT NULL')
        else:
            sql_type = type_map.get(col.lower(), "TEXT")
            columns.append(f'"{col}" {sql_type}')

    if not columns:
        raise ValueError("CSV has no columns to import.")

    schema = ", ".join(columns)

    if primary_key_colname:
        schema += f', PRIMARY KEY ("{primary_key_colname}")'

    return f'CREATE TABLE "{TABLE_NAME}" ({schema});'


def convert(input_path, output_path):
    """
    Read the CSV and import it into SQLite.

    If the database doesn't exist, SQLite creates it.

    If the database already exists, the employees table is dropped
    and recreated before importing the CSV data.
    """

    conn = sqlite3.connect(output_path)
    cur = conn.cursor()

    try:
        # Delete the existing employees table.
        # The database file itself remains untouched.
        cur.execute(f'DROP TABLE IF EXISTS "{TABLE_NAME}"')

        # Open the CSV file.
        with open(
            input_path,
            "r",
            encoding="utf-8-sig",
            newline=""
        ) as f:

            reader = csv.DictReader(f)

            fieldnames = [
                name.strip() if name else name
                for name in (reader.fieldnames or [])
            ]

            if not fieldnames:
                raise ValueError(
                    "CSV file is empty or has no header."
                )

            # Create the employees table.
            schema = build_table_schema(fieldnames)
            cur.execute(schema)

            # Prepare INSERT statement.
            cols = fieldnames

            placeholders = ",".join(
                "?" for _ in cols
            )

            col_sql = ",".join(
                f'"{c}"' for c in cols
            )

            insert_sql = (
                f'INSERT INTO "{TABLE_NAME}" '
                f'({col_sql}) '
                f'VALUES ({placeholders})'
            )

            count = 0

            # Import each row.
            for row in reader:

                # Skip completely empty rows.
                if not any(
                    (row.get(c) or "").strip()
                    for c in cols
                ):
                    continue

                values = []

                for c in cols:
                    raw = row.get(c, "")

                    # Convert counter to an integer.
                    if c.lower() in ("counter", "count"):
                        try:
                            values.append(
                                int(raw or "0")
                            )
                        except (ValueError, TypeError):
                            values.append(0)

                    else:
                        values.append(raw)

                cur.execute(
                    insert_sql,
                    values
                )

                count += 1

        # Save all changes.
        conn.commit()

    except Exception:
        # Undo changes if something goes wrong.
        conn.rollback()
        raise

    finally:
        conn.close()

    return count


def main():

    # ---------------------------------------------------------
    # Check arguments
    # ---------------------------------------------------------

    if len(sys.argv) < 2:
        print("Error: no input CSV file provided.")
        print_usage()
        sys.exit(1)

    if len(sys.argv) > 3:
        print("Error: too many arguments.")
        print_usage()
        sys.exit(1)

    # ---------------------------------------------------------
    # Get arguments
    # ---------------------------------------------------------

    input_path = sys.argv[1]

    # Output database is optional.
    # Default: employees.db
    if len(sys.argv) == 3:
        output_path = sys.argv[2]
    else:
        output_path = DEFAULT_OUTPUT

    # ---------------------------------------------------------
    # Validate input CSV
    # ---------------------------------------------------------

    if not os.path.isfile(input_path):
        print(
            f"Error: input CSV not found: {input_path}"
        )
        sys.exit(1)

    # ---------------------------------------------------------
    # Prevent input/output being the same file
    # ---------------------------------------------------------

    if (
        os.path.abspath(input_path)
        == os.path.abspath(output_path)
    ):
        print(
            "Error: input and output must be "
            "different files."
        )
        sys.exit(1)

    # ---------------------------------------------------------
    # Convert CSV to SQLite
    # ---------------------------------------------------------

    try:
        count = convert(
            input_path,
            output_path
        )

    except Exception as exc:
        print(
            f"Error converting CSV: {exc}"
        )
        sys.exit(1)

    # ---------------------------------------------------------
    # Success
    # ---------------------------------------------------------

    print(
        f"Imported {count} rows."
    )

    print(
        f"Database saved to: {output_path}"
    )


if __name__ == "__main__":
    main()

