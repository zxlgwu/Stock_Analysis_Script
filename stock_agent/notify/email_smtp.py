"""SMTP delivery. Credentials come from the environment, never from the report."""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid

from stock_agent.report.email_report import EmailReport, render_html, render_text, subject_line


class MissingSMTP(RuntimeError):
    pass


def build_message(report: EmailReport) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject_line(report)
    message["From"] = os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER") or "stock-agent@localhost"
    message["To"] = ", ".join(report.recipients)
    message["Message-ID"] = make_msgid(domain="stock-agent.local")
    message.set_content(render_text(report))
    message.add_alternative(render_html(report), subtype="html")
    for cid, path in report.chart_files.items():
        data = path.read_bytes()
        message.get_payload()[1].add_related(data, "image", "png", cid=f"<{cid}>")
    if report.pdf_path is not None and report.pdf_path.exists():
        message.add_attachment(
            report.pdf_path.read_bytes(),
            maintype="application",
            subtype="pdf",
            filename=report.pdf_path.name,
        )
    return message


class EmailNotifier:
    def __init__(self, smtp_factory=None):
        self.smtp_factory = smtp_factory

    def send(self, report: EmailReport) -> str:
        message = build_message(report)
        host = os.environ.get("SMTP_HOST")
        user = os.environ.get("SMTP_USER")
        password = os.environ.get("SMTP_PASSWORD")
        if self.smtp_factory is None and not (host and user and password):
            raise MissingSMTP("Set SMTP_HOST, SMTP_USER, and SMTP_PASSWORD in .env.")
        factory = self.smtp_factory
        if factory is None:
            port = int(os.environ.get("SMTP_PORT") or 587)
            factory = lambda: smtplib.SMTP(host, port)
        with factory() as client:
            if self.smtp_factory is None:
                client.starttls()
                client.login(user, password)
            client.send_message(message)
        return message["Message-ID"]
