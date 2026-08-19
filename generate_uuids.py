"""
generate_uuids.py
=================
Fill the empty `uuid` column in an employee CSV file with unique UUID4 values.

Usage:
    python generate_uuids.py employees.csv [output.csv]

The CSV must have the following column order:
    uuid,first_name,last_name,email

Features:
    - Generates a unique UUID4 for every empty uuid cell.
    - Preserves existing, non-empty UUIDs.
    - Verifies each generated UUID does not already exist in the file.
    - Never overwrites the original input file.
    - Handles empty rows gracefully.
    - Prints a summary of generated UUIDs and the output location.

Uses only the Python standard library.
"""

import csv
import sys
import uuid
import os

# Expected column header for the uuid field.
UUID_COLUMN = "uuid"

# Default output filename when none is provided.
DEFAULT_OUTPUT = "employees_with_uuids.csv"


def collect_existing_uuids(rows):
    """Return a set of all non-empty UUIDs found across the rows."""
    existing = set()
    for row in rows:
        value = (row.get(UUID_COLUMN) or "").strip()
        if value:
            existing.add(value)
    return existing


def generate_unique_uuid(existing):
    """
    Generate a fresh UUID4 that does not already exist in `existing`.

    Adds the new UUID to `existing` and returns it.
    """
    while True:
        new_uuid = str(uuid.uuid4())
        if new_uuid not in existing:
            existing.add(new_uuid)
            return new_uuid


def process_csv(input_path, output_path):
    """Read, fill, and write the CSV. Returns the number of generated UUIDs."""
    generated_count = 0

    with open(input_path, "r", encoding="utf-8-sig", newline="") as infile:
        reader = csv.DictReader(infile)

        # Collect all rows first so we know every existing UUID up front.
        rows = list(reader)

        # Determine / normalize the uuid field name from the header.
        if UUID_COLUMN in reader.fieldnames:
            uuid_field = UUID_COLUMN
        elif reader.fieldnames and reader.fieldnames[0]:
            uuid_field = reader.fieldnames[0]
        else:
            raise ValueError(
                "CSV does not have a valid 'uuid' column. "
                "Expected columns: uuid,first_name,last_name,email"
            )

        # Gather all already-present UUIDs.
        existing_uuids = collect_existing_uuids(rows)

        # Fill in missing UUIDs.
        for row in rows:
            # Skip fully empty rows.
            if not any((value or "").strip() for value in row.values()):
                continue

            current = (row.get(uuid_field) or "").strip()
            if not current:
                row[uuid_field] = generate_unique_uuid(existing_uuids)
                generated_count += 1

    # Write the result to a new file (never overwrites the original).
    with open(output_path, "w", encoding="utf-8", newline="") as outfile:
        fieldnames = reader.fieldnames if reader.fieldnames else [
            UUID_COLUMN, "first_name", "last_name", "email"
        ]
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return generated_count


def main():
    # Parse command-line arguments.
    if len(sys.argv) < 2:
        print("Usage: python generate_uuids.py <input.csv> [output.csv]")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) >= 3 else DEFAULT_OUTPUT

    if not os.path.isfile(input_path):
        print(f"Error: input file not found: {input_path}")
        sys.exit(1)

    if os.path.abspath(input_path) == os.path.abspath(output_path):
        print("Error: output file must differ from the input file.")
        sys.exit(1)

    try:
        generated = process_csv(input_path, output_path)
    except Exception as exc:  # noqa: BLE001 - show a friendly message
        print(f"Error processing CSV: {exc}")
        sys.exit(1)

    print(f"UUIDs generated: {generated}")
    print(f"Output saved to: {output_path}")


if __name__ == "__main__":
    main()
