#!/usr/bin/env python3
"""
CLI-callable email sender.
Usage: python3 email_helper.py --to addr --subject "..." --body "..." [--html body]
"""
import argparse
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD


def send_email(to: str, subject: str, body: str, html_body: str = None):
    if not SMTP_USER or not SMTP_PASSWORD:
        print("WARNING: SMTP_USER / SMTP_PASSWORD not set — email not sent", file=sys.stderr)
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = to
    msg.attach(MIMEText(body, "plain"))
    if html_body:
        msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, to, msg.as_string())

    print(f"Email sent to {to}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--to", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--html", default=None)
    args = parser.parse_args()
    send_email(args.to, args.subject, args.body, args.html)
