"""
Handles desktop popup notifications and email reminders.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    from plyer import notification as plyer_notify
    PLYER_AVAILABLE = True
except ImportError:
    PLYER_AVAILABLE = False


def desktop_notify(title: str, message: str):
    """Show a macOS/desktop notification."""
    if PLYER_AVAILABLE:
        plyer_notify.notify(
            title=title,
            message=message,
            app_name="Finance Tracker",
            timeout=10,
        )
    else:
        print(f"[NOTIFICATION] {title}: {message}")


def send_email(sender: str, password: str, receiver: str,
               subject: str, body: str) -> bool:
    """Send an email via Gmail SMTP. Returns True on success."""
    if not all([sender, password, receiver]):
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = receiver
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, receiver, msg.as_string())
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False


def send_loan_reminder(loans: list[dict], sender: str, password: str, receiver: str):
    """Build and send loan payment reminder."""
    if not loans:
        return

    lines = ["Hi! This is your monthly loan payment reminder.\n"]
    for loan in loans:
        lines.append(
            f"  • {loan['name']}: EMI = {loan['currency']} {loan['emi']:,.2f}  |  "
            f"Remaining balance = {loan['currency']} {loan['remaining_balance']:,.2f}"
        )
    lines.append("\nStay on top of your payments. Good luck!")
    body = "\n".join(lines)

    subject = "Finance Tracker — Monthly Loan Payment Reminder"
    desktop_notify("Loan Payment Due", f"You have {len(loans)} loan(s) due this month.")
    send_email(sender, password, receiver, subject, body)