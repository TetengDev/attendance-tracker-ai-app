from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, date, datetime
from typing import Any, cast

from jinja2 import Template

logger = logging.getLogger("attendance_tracker")

try:
    import xlsxwriter  # type: ignore[import-untyped]
except ImportError:
    xlsxwriter = None

try:
    from weasyprint import HTML  # type: ignore[import-untyped]
except (ImportError, OSError, Exception) as exc:  # noqa: BLE001
    logger.warning("WeasyPrint could not be imported: %s", exc)
    HTML = None

# Jinja2 template for rendering high-quality reports to HTML/PDF
PDF_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{{ title }}</title>
  <style>
    @page {
      size: A4 landscape;
      margin: 1.2cm;
      @bottom-right {
        content: "Page " counter(page) " of " counter(pages);
        font-size: 8pt;
        font-family: sans-serif;
        color: #718096;
      }
      @bottom-left {
        content: "{{ date_str }} | Attendance Tracker AI";
        font-size: 8pt;
        font-family: sans-serif;
        color: #718096;
      }
    }
    body {
      font-family: Arial, sans-serif;
      color: #2D3748;
      margin: 0;
      padding: 0;
    }
    .header {
      margin-bottom: 20px;
      border-bottom: 2px solid #E2E8F0;
      padding-bottom: 10px;
    }
    .title {
      font-size: 22px;
      font-weight: bold;
      color: #1A365D;
      margin: 0;
    }
    .subtitle {
      font-size: 12px;
      color: #4A5568;
      margin: 5px 0 0 0;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 10px;
      font-size: 8pt;
    }
    th {
      background-color: #1A365D;
      color: white;
      font-weight: bold;
      text-align: left;
      padding: 6px;
      border: 1px solid #CBD5E0;
    }
    td {
      padding: 5px 6px;
      border: 1px solid #E2E8F0;
      text-align: left;
      word-wrap: break-word;
      max-width: 180px;
    }
    tr:nth-child(even) td {
      background-color: #F7FAFC;
    }
    .badge {
      display: inline-block;
      padding: 2px 4px;
      border-radius: 3px;
      font-size: 7.5pt;
      font-weight: bold;
      text-transform: uppercase;
    }
    .badge-on_time { background-color: #C6F6D5; color: #22543D; }
    .badge-complete { background-color: #C6F6D5; color: #22543D; }
    .badge-late { background-color: #FED7D7; color: #742A2A; }
    .badge-absent { background-color: #FFF5F5; color: #9B2C2C; }
    .badge-excused { background-color: #E2E8F0; color: #4A5568; }
    .badge-holiday { background-color: #E2E8F0; color: #4A5568; }
    .badge-not_scheduled { background-color: #EDF2F7; color: #4A5568; }
    .badge-present_unscheduled { background-color: #EBF8FF; color: #2B6CB0; }
    .badge-pending { background-color: #FEFCBF; color: #744210; }
    .badge-incomplete { background-color: #FEEBC8; color: #7B341E; }
  </style>
</head>
<body>
  <div class="header">
    <h1 class="title">{{ title }}</h1>
    {% if subtitle %}
      <p class="subtitle">{{ subtitle }}</p>
    {% endif %}
  </div>
  <table>
    <thead>
      <tr>
        {% for header in headers %}
          <th>{{ header.replace('_', ' ').title() }}</th>
        {% endfor %}
      </tr>
    </thead>
    <tbody>
      {% for row in rows %}
        <tr>
          {% for header in headers %}
            <td>
              {% set val = row.get(header) %}
              {% if header == 'status' and val %}
                <span class="badge badge-{{ val }}">{{ val.replace('_', ' ') }}</span>
              {% elif header in ['actual_in', 'actual_out', 'checked_in_at', 'expected_start_at', 'expected_end_at', 'last_active'] and val %}
                {{ val.strftime('%Y-%m-%d %H:%M:%S') if hasattr(val, 'strftime') else val }}
              {% elif header in ['business_date'] and val %}
                {{ val.strftime('%Y-%m-%d') if hasattr(val, 'strftime') else val }}
              {% elif val is none %}
                
              {% else %}
                {{ val }}
              {% endif %}
            </td>
          {% endfor %}
        </tr>
      {% endfor %}
    </tbody>
  </table>
</body>
</html>
"""


def stream_csv(rows: list[dict[str, Any]], headers: list[str]) -> Any:
    """Streams CSV output with a UTF-8 BOM first to prevent Excel encoding issues."""
    yield b"\xef\xbb\xbf"  # UTF-8 BOM

    # Write headers
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([h.replace("_", " ").title() for h in headers])
    yield output.getvalue().encode("utf-8")

    for row in rows:
        output = io.StringIO()
        writer = csv.writer(output)
        formatted_row = []
        for h in headers:
            val = row.get(h)
            if isinstance(val, datetime):
                formatted_row.append(val.strftime("%Y-%m-%d %H:%M:%S"))
            elif isinstance(val, date):
                formatted_row.append(val.strftime("%Y-%m-%d"))
            elif val is None:
                formatted_row.append("")
            else:
                formatted_row.append(str(val))
        writer.writerow(formatted_row)
        yield output.getvalue().encode("utf-8")


def render_xlsx(
    rows: list[dict[str, Any]], headers: list[str], report_title: str = "Report"
) -> bytes:
    """Generates an Excel file in memory using xlsxwriter with constant_memory enabled."""
    if xlsxwriter is None:
        raise ImportError("xlsxwriter package is missing")

    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True, "constant_memory": True})
    sheet_name = report_title[:31].replace("[", "").replace("]", "").replace(":", "")
    worksheet = workbook.add_worksheet(name=sheet_name)

    # Styling formats
    header_format = workbook.add_format(
        {
            "bold": True,
            "font_color": "white",
            "bg_color": "#1A365D",
            "border": 1,
            "align": "center",
            "valign": "vcenter",
        }
    )

    data_format = workbook.add_format(
        {
            "border": 1,
            "align": "left",
            "valign": "vcenter",
        }
    )

    # Write header columns
    for col_num, header in enumerate(headers):
        label = header.replace("_", " ").title()
        worksheet.write(0, col_num, label, header_format)

    # Write data rows
    for row_num, row in enumerate(rows, start=1):
        for col_num, header in enumerate(headers):
            val = row.get(header)
            if isinstance(val, datetime):
                worksheet.write_string(
                    row_num, col_num, val.strftime("%Y-%m-%d %H:%M:%S"), data_format
                )
            elif isinstance(val, date):
                worksheet.write_string(row_num, col_num, val.strftime("%Y-%m-%d"), data_format)
            elif val is None:
                worksheet.write_string(row_num, col_num, "", data_format)
            else:
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    worksheet.write_number(row_num, col_num, val, data_format)
                else:
                    worksheet.write_string(row_num, col_num, str(val), data_format)

    workbook.close()
    output.seek(0)
    return output.read()


def render_pdf(
    rows: list[dict[str, Any]], headers: list[str], report_title: str = "Report", subtitle: str = ""
) -> bytes:
    """Renders HTML layout of rows and outputs PDF binary using WeasyPrint (Pango-only)."""
    if HTML is None:
        raise ImportError("weasyprint package is missing or misconfigured")

    template = Template(PDF_HTML_TEMPLATE)
    date_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

    # Render template with helpers built-in
    html_content = template.render(
        title=report_title,
        subtitle=subtitle,
        headers=headers,
        rows=rows,
        date_str=date_str,
        hasattr=hasattr,
    )

    html = HTML(string=html_content)
    pdf_bytes = html.write_pdf()
    return cast(bytes, pdf_bytes)
