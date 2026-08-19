
"""
Employee Awareness Tracking Server
===================================

Tracks which employee opens their personalized awareness link.

Employee link:
    http://SERVER:8000/?uuid=<employee_uuid>

Admin links:
    http://SERVER:8000/links

Tracking report:
    http://SERVER:8000/report

CLI report:
    python server.py employees.db --report

Usage:
    python server.py [database.db] [port] [host]

Examples:
    python server.py employees.db
    python server.py employees.db 8080
    python server.py employees.db 8080 127.0.0.1
    python server.py employees.db --report

Database:
    employees
        uuid
        first_name
        last_name
        email
        counter

    visits
        id
        uuid
        visited_at

Uses only the Python standard library.
"""

import os
import sqlite3
import sys
import signal
import threading
import json
import html
import time

from datetime import datetime, timezone

from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer
)

from urllib.parse import (
    urlparse,
    parse_qs,
    quote
)


# ===========================================================================
# Configuration
# ===========================================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

STATIC_DIR = os.path.join(
    BASE_DIR,
    "form_page"
)

DB_FILE = None

TABLE_NAME = "employees"
VISITS_TABLE = "visits"

UUID_COLUMN = "uuid"
COUNTER_COLUMN = "counter"

TRACKING_PARAMETER = "uuid"

DEFAULT_PORT = 8000
DEFAULT_HOST = "0.0.0.0"

# SQLite configuration
SQLITE_TIMEOUT = 30
SQLITE_RETRIES = 5

# Protect SQLite operations inside this process.
db_lock = threading.RLock()


# ===========================================================================
# SQLite connection
# ===========================================================================

def get_db_connection():
    """
    Open a SQLite connection configured for concurrent access.
    """

    conn = sqlite3.connect(
        DB_FILE,
        timeout=SQLITE_TIMEOUT
    )

    # Wait up to 30 seconds if another connection is writing.
    conn.execute(
        "PRAGMA busy_timeout = 30000"
    )

    # WAL allows readers and writers to work concurrently.
    conn.execute(
        "PRAGMA journal_mode = WAL"
    )

    # Good balance between performance and durability.
    conn.execute(
        "PRAGMA synchronous = NORMAL"
    )

    return conn


# ===========================================================================
# Database initialization
# ===========================================================================

def initialize_database():
    """
    Create the visits table if it does not already exist.
    """

    with db_lock:

        conn = get_db_connection()

        try:

            cur = conn.cursor()

            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS "{VISITS_TABLE}" (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid TEXT NOT NULL,
                    visited_at TEXT NOT NULL
                )
                """
            )

            conn.commit()

        finally:

            conn.close()


# ===========================================================================
# Get employee
# ===========================================================================

def get_employee(uuid_value):
    """
    Find an employee by UUID.

    Returns a dictionary or None.
    """

    with db_lock:

        conn = get_db_connection()

        try:

            cur = conn.cursor()

            cur.execute(
                f"""
                SELECT
                    uuid,
                    first_name,
                    last_name,
                    email,
                    counter
                FROM "{TABLE_NAME}"
                WHERE "{UUID_COLUMN}" = ?
                """,
                (uuid_value,)
            )

            row = cur.fetchone()

            if row is None:
                return None

            return {
                "uuid": row[0],
                "first_name": row[1] or "",
                "last_name": row[2] or "",
                "email": row[3] or "",
                "counter": row[4] or 0
            }

        finally:

            conn.close()


# ===========================================================================
# Get all employees
# ===========================================================================

def get_all_employees():
    """
    Return all employees from the database.
    """

    with db_lock:

        conn = get_db_connection()

        try:

            cur = conn.cursor()

            cur.execute(
                f"""
                SELECT
                    uuid,
                    first_name,
                    last_name,
                    email,
                    counter
                FROM "{TABLE_NAME}"
                ORDER BY first_name, last_name
                """
            )

            rows = cur.fetchall()

            employees = []

            for row in rows:

                employees.append({
                    "uuid": row[0],
                    "first_name": row[1] or "",
                    "last_name": row[2] or "",
                    "email": row[3] or "",
                    "counter": row[4] or 0
                })

            return employees

        finally:

            conn.close()


# ===========================================================================
# Track visit
# ===========================================================================

def track_visit(uuid_value):
    """
    Increment an employee's counter and record the visit.

    Returns:
        Employee dictionary with updated counter.

    Returns:
        None if UUID does not exist.
    """

    last_error = None

    for attempt in range(SQLITE_RETRIES):

        try:

            with db_lock:

                conn = get_db_connection()

                try:

                    cur = conn.cursor()

                    # -------------------------------------------------------
                    # Find employee
                    # -------------------------------------------------------

                    cur.execute(
                        f"""
                        SELECT
                            uuid,
                            first_name,
                            last_name,
                            email,
                            counter
                        FROM "{TABLE_NAME}"
                        WHERE "{UUID_COLUMN}" = ?
                        """,
                        (uuid_value,)
                    )

                    row = cur.fetchone()

                    if row is None:

                        conn.rollback()

                        return None

                    # -------------------------------------------------------
                    # Increment counter
                    # -------------------------------------------------------

                    cur.execute(
                        f"""
                        UPDATE "{TABLE_NAME}"
                        SET "{COUNTER_COLUMN}" =
                            COALESCE("{COUNTER_COLUMN}", 0) + 1
                        WHERE "{UUID_COLUMN}" = ?
                        """,
                        (uuid_value,)
                    )

                    # -------------------------------------------------------
                    # Record visit
                    # -------------------------------------------------------

                    visited_at = datetime.now(
                        timezone.utc
                    ).isoformat()

                    cur.execute(
                        f"""
                        INSERT INTO "{VISITS_TABLE}"
                            (uuid, visited_at)
                        VALUES
                            (?, ?)
                        """,
                        (
                            uuid_value,
                            visited_at
                        )
                    )

                    # -------------------------------------------------------
                    # Commit both operations together
                    # -------------------------------------------------------

                    conn.commit()

                    new_counter = (
                        (row[4] or 0) + 1
                    )

                    return {
                        "uuid": row[0],
                        "first_name": row[1] or "",
                        "last_name": row[2] or "",
                        "email": row[3] or "",
                        "counter": new_counter
                    }

                except Exception:

                    conn.rollback()

                    raise

                finally:

                    conn.close()

        except sqlite3.OperationalError as exc:

            last_error = exc

            error_text = str(exc).lower()

            if (
                "database is locked"
                not in error_text
            ):

                raise

            # Retry progressively.
            delay = 0.5 * (
                attempt + 1
            )

            print(
                f"SQLite database locked. "
                f"Retrying in {delay:.1f}s..."
            )

            time.sleep(
                delay
            )

    raise last_error


# ===========================================================================
# Visit history
# ===========================================================================

def get_visit_history():
    """
    Return all recorded visits.
    """

    with db_lock:

        conn = get_db_connection()

        try:

            cur = conn.cursor()

            cur.execute(
                f"""
                SELECT
                    v.id,
                    v.uuid,
                    v.visited_at,
                    e.first_name,
                    e.last_name,
                    e.email
                FROM "{VISITS_TABLE}" v
                LEFT JOIN "{TABLE_NAME}" e
                    ON e.uuid = v.uuid
                ORDER BY v.visited_at DESC
                """
            )

            rows = cur.fetchall()

            visits = []

            for row in rows:

                visits.append({
                    "id": row[0],
                    "uuid": row[1],
                    "visited_at": row[2],
                    "first_name": row[3] or "",
                    "last_name": row[4] or "",
                    "email": row[5] or ""
                })

            return visits

        finally:

            conn.close()


# ===========================================================================
# HTML helpers
# ===========================================================================

def escape(value):
    return html.escape(
        str(value),
        quote=True
    )


def get_employee_name(employee):
    name = (
        f"{employee['first_name']} "
        f"{employee['last_name']}"
    ).strip()

    return name or "Unknown"


def build_tracking_url(
    request,
    uuid_value
):
    """
    Build personalized tracking URL.

    Example:
        http://server:8000/?uuid=xxxxxxxx
    """

    host = request.headers.get(
        "Host",
        f"localhost:{DEFAULT_PORT}"
    )

    return (
        f"http://{host}/?"
        f"{TRACKING_PARAMETER}="
        f"{quote(uuid_value)}"
    )


# ===========================================================================
# Admin Links Page
# ===========================================================================

def generate_links_page(request):

    employees = get_all_employees()

    rows = []

    for employee in employees:

        name = get_employee_name(
            employee
        )

        tracking_url = build_tracking_url(
            request,
            employee["uuid"]
        )

        uuid_safe = escape(
            employee["uuid"]
        )

        row = f"""
        <tr>
            <td>
                <strong>{escape(name)}</strong>
            </td>

            <td>
                {escape(employee["email"])}
            </td>

            <td>
                <code>{uuid_safe}</code>
            </td>

            <td>
                <span class="count">
                    {employee["counter"]}
                </span>
            </td>

            <td>
                <div class="link-box">

                    <input
                        type="text"
                        readonly
                        value="{escape(tracking_url)}"
                        id="link-{uuid_safe}"
                    >

                    <button
                        onclick="copyLink(
                            'link-{uuid_safe}',
                            this
                        )"
                    >
                        Copy
                    </button>

                    <a
                        href="{escape(tracking_url)}"
                        target="_blank"
                    >
                        Open
                    </a>

                </div>
            </td>
        </tr>
        """

        rows.append(row)

    table_rows = "".join(rows)

    total_employees = len(
        employees
    )

    opened_employees = sum(
        1
        for employee in employees
        if employee["counter"] > 0
    )

    total_visits = sum(
        employee["counter"]
        for employee in employees
    )

    return f"""
<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>Employee Tracking Links</title>

<style>

* {{
    box-sizing: border-box;
}}

body {{
    margin: 0;
    font-family:
        Arial,
        Helvetica,
        sans-serif;

    background: #f4f6f8;
    color: #1f2937;
}}

.container {{
    max-width: 1500px;
    margin: auto;
    padding: 40px 25px;
}}

.header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 30px;
}}

.header h1 {{
    margin: 0;
    font-size: 30px;
}}

.header p {{
    color: #6b7280;
}}

.nav {{
    display: flex;
    gap: 10px;
}}

.nav a {{
    text-decoration: none;
    padding: 10px 16px;
    border-radius: 8px;
    background: #111827;
    color: white;
}}

.stats {{
    display: grid;
    grid-template-columns:
        repeat(3, 1fr);

    gap: 20px;
    margin-bottom: 30px;
}}

.stat {{
    background: white;
    border-radius: 12px;
    padding: 25px;

    box-shadow:
        0 2px 8px
        rgba(0, 0, 0, 0.06);
}}

.stat-number {{
    font-size: 32px;
    font-weight: bold;
}}

.stat-label {{
    color: #6b7280;
    margin-top: 5px;
}}

.search {{
    width: 100%;
    padding: 14px 16px;

    border:
        1px solid #d1d5db;

    border-radius: 9px;

    margin-bottom: 20px;

    font-size: 15px;
}}

.table-container {{
    background: white;
    border-radius: 12px;
    overflow-x: auto;

    box-shadow:
        0 2px 8px
        rgba(0, 0, 0, 0.06);
}}

table {{
    width: 100%;
    border-collapse: collapse;
}}

th {{
    background: #111827;
    color: white;
    text-align: left;
    padding: 15px;
    white-space: nowrap;
}}

td {{
    padding: 15px;
    border-bottom:
        1px solid #e5e7eb;
    vertical-align: middle;
}}

tr:hover {{
    background: #f9fafb;
}}

code {{
    font-size: 12px;
    color: #4b5563;
}}

.count {{
    display: inline-flex;

    min-width: 35px;
    height: 35px;

    justify-content: center;
    align-items: center;

    border-radius: 50%;

    background: #e5e7eb;

    font-weight: bold;
}}

.link-box {{
    display: flex;
    gap: 7px;

    min-width: 450px;
}}

.link-box input {{
    flex: 1;

    padding: 9px;

    border:
        1px solid #d1d5db;

    border-radius: 6px;

    font-size: 12px;
}}

button,
.link-box a {{
    border: none;

    padding:
        9px 13px;

    border-radius: 6px;

    background: #111827;

    color: white;

    cursor: pointer;

    text-decoration: none;

    font-size: 13px;
}}

button:hover,
.link-box a:hover {{
    opacity: 0.85;
}}

@media (max-width: 800px) {{

    .stats {{
        grid-template-columns: 1fr;
    }}

    .header {{
        flex-direction: column;
        align-items: flex-start;
        gap: 15px;
    }}

}}

</style>

</head>

<body>

<div class="container">

    <div class="header">

        <div>

            <h1>
                Employee Tracking Links
            </h1>

            <p>
                Personalized awareness links
                for employees.
            </p>

        </div>

        <div class="nav">

            <a href="/links">
                Links
            </a>

            <a href="/report">
                Report
            </a>

        </div>

    </div>


    <div class="stats">

        <div class="stat">

            <div class="stat-number">
                {total_employees}
            </div>

            <div class="stat-label">
                Total Employees
            </div>

        </div>


        <div class="stat">

            <div class="stat-number">
                {opened_employees}
            </div>

            <div class="stat-label">
                Employees Who Opened
            </div>

        </div>


        <div class="stat">

            <div class="stat-number">
                {total_visits}
            </div>

            <div class="stat-label">
                Total Opens
            </div>

        </div>

    </div>


    <input
        class="search"
        id="search"
        type="text"
        placeholder="Search employee, email, or UUID..."
        oninput="filterEmployees()"
    >


    <div class="table-container">

        <table id="employees">

            <thead>

                <tr>

                    <th>Employee</th>
                    <th>Email</th>
                    <th>UUID</th>
                    <th>Opens</th>
                    <th>Personalized Link</th>

                </tr>

            </thead>

            <tbody>

                {table_rows}

            </tbody>

        </table>

    </div>

</div>


<script>

function filterEmployees() {{

    const input =
        document
            .getElementById("search")
            .value
            .toLowerCase();

    const rows =
        document.querySelectorAll(
            "#employees tbody tr"
        );

    rows.forEach(row => {{

        const text =
            row.innerText.toLowerCase();

        row.style.display =
            text.includes(input)
                ? ""
                : "none";

    }});
}}


function copyLink(id, button) {{

    const input =
        document.getElementById(id);

    navigator.clipboard
        .writeText(input.value)
        .then(() => {{

            const original =
                button.innerText;

            button.innerText =
                "Copied!";

            setTimeout(() => {{

                button.innerText =
                    original;

            }}, 1200);

        }})
        .catch(() => {{

            input.select();

            document.execCommand(
                "copy"
            );

            button.innerText =
                "Copied!";

            setTimeout(() => {{

                button.innerText =
                    "Copy";

            }}, 1200);

        }});
}}

</script>

</body>

</html>
"""


# ===========================================================================
# Report Page
# ===========================================================================

def generate_report_page():

    employees = get_all_employees()

    visits = get_visit_history()

    opened = [
        employee
        for employee in employees
        if employee["counter"] > 0
    ]

    employee_rows = []

    for employee in opened:

        name = get_employee_name(
            employee
        )

        employee_rows.append(
            f"""
            <tr>

                <td>
                    {escape(name)}
                </td>

                <td>
                    {escape(employee["email"])}
                </td>

                <td>
                    <code>
                        {escape(employee["uuid"])}
                    </code>
                </td>

                <td>
                    <strong>
                        {employee["counter"]}
                    </strong>
                </td>

            </tr>
            """
        )

    visit_rows = []

    for visit in visits:

        name = (
            f"{visit['first_name']} "
            f"{visit['last_name']}"
        ).strip()

        if not name:
            name = "Unknown"

        visit_rows.append(
            f"""
            <tr>

                <td>
                    {escape(visit["visited_at"])}
                </td>

                <td>
                    {escape(name)}
                </td>

                <td>
                    {escape(visit["email"])}
                </td>

                <td>
                    <code>
                        {escape(visit["uuid"])}
                    </code>
                </td>

            </tr>
            """
        )

    employee_html = (
        "".join(employee_rows)
        if employee_rows
        else
        """
        <tr>
            <td colspan="4">
                No employees have opened their links yet.
            </td>
        </tr>
        """
    )

    visit_html = (
        "".join(visit_rows)
        if visit_rows
        else
        """
        <tr>
            <td colspan="4">
                No visits recorded.
            </td>
        </tr>
        """
    )

    return f"""
<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>Tracking Report</title>

<style>

body {{
    margin: 0;

    font-family:
        Arial,
        Helvetica,
        sans-serif;

    background: #f4f6f8;
    color: #1f2937;
}}

.container {{
    max-width: 1400px;
    margin: auto;
    padding: 40px 25px;
}}

header {{
    display: flex;
    justify-content: space-between;
    align-items: center;

    margin-bottom: 30px;
}}

h1 {{
    margin: 0;
}}

header a {{
    text-decoration: none;

    color: white;

    background: #111827;

    padding: 10px 16px;

    border-radius: 8px;
}}

.section {{
    background: white;

    margin-bottom: 30px;

    border-radius: 12px;

    overflow-x: auto;

    box-shadow:
        0 2px 8px
        rgba(0, 0, 0, 0.06);
}}

.section h2 {{
    padding: 20px;
    margin: 0;

    border-bottom:
        1px solid #e5e7eb;
}}

table {{
    width: 100%;
    border-collapse: collapse;
}}

th {{
    background: #111827;
    color: white;

    text-align: left;

    padding: 14px;
}}

td {{
    padding: 14px;

    border-bottom:
        1px solid #e5e7eb;
}}

code {{
    font-size: 12px;
}}

</style>

</head>

<body>

<div class="container">

<header>

    <div>

        <h1>
            Tracking Report
        </h1>

        <p>
            Employees who opened their personalized links.
        </p>

    </div>

    <a href="/links">
        Back to Links
    </a>

</header>


<div class="section">

<h2>
    Employees Who Opened
</h2>

<table>

<thead>

<tr>

<th>Employee</th>
<th>Email</th>
<th>UUID</th>
<th>Opens</th>

</tr>

</thead>

<tbody>

{employee_html}

</tbody>

</table>

</div>


<div class="section">

<h2>
    Visit History
</h2>

<table>

<thead>

<tr>

<th>Time</th>
<th>Employee</th>
<th>Email</th>
<th>UUID</th>

</tr>

</thead>

<tbody>

{visit_html}

</tbody>

</table>

</div>

</div>

</body>

</html>
"""


# ===========================================================================
# HTTP Handler
# ===========================================================================

class CampaignHandler(
    BaseHTTPRequestHandler
):

    server_version = (
        "EmployeeTrackingServer/1.0"
    )

    def log_message(
        self,
        format,
        *args
    ):

        sys.stdout.write(
            "[%s] %s\n"
            % (
                self.log_date_time_string(),
                format % args
            )
        )

    # -----------------------------------------------------------------------
    # GET
    # -----------------------------------------------------------------------

    def do_GET(self):

        parsed = urlparse(
            self.path
        )

        path = parsed.path

        # ===============================================================
        # Admin links
        # ===============================================================

        if path == "/links":

            self.send_html(
                generate_links_page(
                    self
                )
            )

            return

        # ===============================================================
        # Report
        # ===============================================================

        if path == "/report":

            self.send_html(
                generate_report_page()
            )

            return

        # ===============================================================
        # JSON links
        # ===============================================================

        if path == "/api/links":

            employees = get_all_employees()

            self.send_json(
                employees
            )

            return

        # ===============================================================
        # JSON report
        # ===============================================================

        if path == "/api/report":

            self.send_json({
                "employees":
                    get_all_employees(),

                "visits":
                    get_visit_history()
            })

            return

        # ===============================================================
        # Employee tracking page
        # ===============================================================

        if path in (
            "/",
            "/index.html",
            "/MainForm.html"
        ):

            query = parse_qs(
                parsed.query
            )

            uuid_value = query.get(
                TRACKING_PARAMETER,
                [""]
            )[0].strip()

            if uuid_value:

                try:

                    employee = track_visit(
                        uuid_value
                    )

                    if employee:

                        name = get_employee_name(
                            employee
                        )

                        self.log_message(
                            "OPENED: %s | %s | "
                            "UUID: %s | Count: %d",
                            name,
                            employee["email"],
                            employee["uuid"],
                            employee["counter"]
                        )

                    else:

                        self.log_message(
                            "UNKNOWN UUID: %s",
                            uuid_value
                        )

                except Exception as exc:

                    self.log_message(
                        "TRACKING ERROR: %s",
                        exc
                    )

            else:

                self.log_message(
                    "PAGE OPENED WITHOUT UUID"
                )

        # ===============================================================
        # Static files
        # ===============================================================

        self.serve_static(
            path
        )

    # -----------------------------------------------------------------------
    # HTML response
    # -----------------------------------------------------------------------

    def send_html(
        self,
        body
    ):

        encoded = body.encode(
            "utf-8"
        )

        self.send_response(
            200
        )

        self.send_header(
            "Content-Type",
            "text/html; charset=utf-8"
        )

        self.send_header(
            "Content-Length",
            str(len(encoded))
        )

        self.send_header(
            "Cache-Control",
            "no-cache, no-store, must-revalidate"
        )

        self.end_headers()

        self.wfile.write(
            encoded
        )

    # -----------------------------------------------------------------------
    # JSON response
    # -----------------------------------------------------------------------

    def send_json(
        self,
        data
    ):

        body = json.dumps(
            data,
            indent=2
        ).encode(
            "utf-8"
        )

        self.send_response(
            200
        )

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.send_header(
            "Cache-Control",
            "no-cache"
        )

        self.end_headers()

        self.wfile.write(
            body
        )

    # -----------------------------------------------------------------------
    # Static files
    # -----------------------------------------------------------------------

    def serve_static(
        self,
        path
    ):

        if path in (
            "/",
            "/index.html"
        ):

            rel_path = "MainForm.html"

        else:

            rel_path = path.lstrip("/")

            if (
                ".." in rel_path
                or not rel_path
            ):

                rel_path = "MainForm.html"

        full_path = os.path.join(
            STATIC_DIR,
            rel_path
        )

        static_real = os.path.realpath(
            STATIC_DIR
        )

        file_real = os.path.realpath(
            full_path
        )

        # Prevent directory traversal.
        if not (
            file_real == static_real
            or file_real.startswith(
                static_real + os.sep
            )
        ):

            self.send_error(
                403,
                "Forbidden"
            )

            return

        if not os.path.isfile(
            file_real
        ):

            self.send_error(
                404,
                "File not found"
            )

            return

        content_type = (
            self.guess_content_type(
                file_real
            )
        )

        try:

            with open(
                file_real,
                "rb"
            ) as f:

                body = f.read()

        except OSError:

            self.send_error(
                500,
                "Could not read file"
            )

            return

        self.send_response(
            200
        )

        self.send_header(
            "Content-Type",
            content_type
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.send_header(
            "Cache-Control",
            "no-cache, no-store, must-revalidate"
        )

        self.end_headers()

        self.wfile.write(
            body
        )

    # -----------------------------------------------------------------------
    # Content type
    # -----------------------------------------------------------------------

    @staticmethod
    def guess_content_type(
        path
    ):

        ext = os.path.splitext(
            path
        )[1].lower()

        return {
            ".html":
                "text/html; charset=utf-8",

            ".css":
                "text/css; charset=utf-8",

            ".js":
                "application/javascript; charset=utf-8",

            ".png":
                "image/png",

            ".jpg":
                "image/jpeg",

            ".jpeg":
                "image/jpeg",

            ".gif":
                "image/gif",

            ".svg":
                "image/svg+xml",

            ".ico":
                "image/x-icon",

        }.get(
            ext,
            "application/octet-stream"
        )


# ===========================================================================
# Main
# ===========================================================================

def main():

    global DB_FILE

    # -----------------------------------------------------------------------
    # Require database argument
    # -----------------------------------------------------------------------

    if len(sys.argv) < 2:

        print(
            "Error: database file is required."
        )

        print()

        print(
            "Usage:"
        )

        print(
            "  python server.py [database.db] [port] [host]"
        )

        print()

        print(
            "Examples:"
        )

        print(
            "  python server.py employees.db"
        )

        print(
            "  python server.py employees.db 8080"
        )

        print(
            "  python server.py employees.db 8080 127.0.0.1"
        )

        print()

        print(
            "CLI report:"
        )

        print(
            "  python server.py employees.db --report"
        )

        sys.exit(1)

    # -----------------------------------------------------------------------
    # CLI report
    # -----------------------------------------------------------------------

    if (
        len(sys.argv) == 3
        and sys.argv[2] == "--report"
    ):

        DB_FILE = os.path.abspath(
            sys.argv[1]
        )

        if not os.path.isfile(
            DB_FILE
        ):

            print(
                f"Error: database not found: {DB_FILE}"
            )

            sys.exit(1)

        initialize_database()

        employees = get_all_employees()
        visits = get_visit_history()

        opened = [
            employee
            for employee in employees
            if employee["counter"] > 0
        ]

        print()
        print("=" * 80)
        print("EMPLOYEES WHO OPENED THEIR LINKS")
        print("=" * 80)

        if not opened:

            print(
                "No employees have opened their links yet."
            )

        else:

            for employee in opened:

                name = get_employee_name(
                    employee
                )

                print(
                    f"{name} | "
                    f"{employee['email']} | "
                    f"Opens: {employee['counter']} | "
                    f"UUID: {employee['uuid']}"
                )

        print()
        print(
            f"Employees opened: {len(opened)}"
        )

        print(
            f"Total visits: "
            f"{sum(e['counter'] for e in employees)}"
        )

        print()
        print("=" * 80)
        print("VISIT HISTORY")
        print("=" * 80)

        for visit in visits:

            name = (
                f"{visit['first_name']} "
                f"{visit['last_name']}"
            ).strip()

            print(
                f"{visit['visited_at']} | "
                f"{name or 'Unknown'} | "
                f"{visit['email']} | "
                f"{visit['uuid']}"
            )

        print("=" * 80)

        return

    # -----------------------------------------------------------------------
    # Validate number of arguments
    # -----------------------------------------------------------------------

    if len(sys.argv) > 4:

        print(
            "Error: too many arguments."
        )

        print(
            "Usage:"
        )

        print(
            "  python server.py [database.db] [port] [host]"
        )

        sys.exit(1)

    # -----------------------------------------------------------------------
    # Database
    # -----------------------------------------------------------------------

    DB_FILE = os.path.abspath(
        sys.argv[1]
    )

    if not os.path.isfile(
        DB_FILE
    ):

        print(
            f"Error: database not found: {DB_FILE}"
        )

        sys.exit(1)

    # -----------------------------------------------------------------------
    # Port
    # -----------------------------------------------------------------------

    port = DEFAULT_PORT

    if len(sys.argv) >= 3:

        try:

            port = int(
                sys.argv[2]
            )

        except ValueError:

            print(
                f"Error: invalid port: {sys.argv[2]}"
            )

            sys.exit(1)

        if not (
            1 <= port <= 65535
        ):

            print(
                "Error: port must be between "
                "1 and 65535."
            )

            sys.exit(1)

    # -----------------------------------------------------------------------
    # Host
    # -----------------------------------------------------------------------

    host = DEFAULT_HOST

    if len(sys.argv) >= 4:

        host = sys.argv[3]

    # -----------------------------------------------------------------------
    # Initialize database
    # -----------------------------------------------------------------------

    try:

        initialize_database()

        # Verify employees table exists.
        with get_db_connection() as conn:

            conn.execute(
                f"""
                SELECT uuid, counter
                FROM "{TABLE_NAME}"
                LIMIT 1
                """
            )

    except Exception as exc:

        print(
            f"Error initializing database: {exc}"
        )

        sys.exit(1)

    # -----------------------------------------------------------------------
    # Start server
    # -----------------------------------------------------------------------

    try:

        server = ThreadingHTTPServer(
            (
                host,
                port
            ),
            CampaignHandler
        )

    except OSError as exc:

        print(
            f"Error starting server: {exc}"
        )

        sys.exit(1)

    # -----------------------------------------------------------------------
    # Shutdown
    # -----------------------------------------------------------------------

    def shutdown_handler(
        signum,
        frame
    ):

        print(
            "\nShutting down server..."
        )

        server.shutdown()

    signal.signal(
        signal.SIGINT,
        shutdown_handler
    )

    signal.signal(
        signal.SIGTERM,
        shutdown_handler
    )

    # -----------------------------------------------------------------------
    # Startup information
    # -----------------------------------------------------------------------

    print()

    print("=" * 70)

    print(
        " Employee Awareness Tracking Server"
    )

    print("=" * 70)

    print(
        f"Database:     {DB_FILE}"
    )

    print(
        f"Static files: {STATIC_DIR}"
    )

    print(
        f"Listening:    {host}:{port}"
    )

    print()

    print(
        "Employee link:"
    )

    print(
        f"http://<server>:{port}/?uuid=<employee_uuid>"
    )

    print()

    print(
        "Admin links:"
    )

    print(
        f"http://<server>:{port}/links"
    )

    print()

    print(
        "Web report:"
    )

    print(
        f"http://<server>:{port}/report"
    )

    print()

    print(
        "CLI report:"
    )

    print(
        f"python server.py {DB_FILE} --report"
    )

    print()

    print(
        "SQLite WAL mode: enabled"
    )

    print(
        "SQLite busy timeout: 30 seconds"
    )

    print(
        "Press Ctrl+C to stop."
    )

    print("=" * 70)

    # -----------------------------------------------------------------------
    # Run
    # -----------------------------------------------------------------------

    try:

        server.serve_forever()

    except KeyboardInterrupt:

        pass

    finally:

        server.server_close()

        print(
            "Server stopped."
        )


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    main()

