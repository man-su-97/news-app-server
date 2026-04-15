import smtplib
from jinja2 import Template
from email.mime.text import MIMEText
from app.core.config import settings

def send_email_otp(to_email: str, otp: str) -> bool:
  sender_email = settings.SENDER_EMAIL
  sender_password = settings.SENDER_PASSWORD

  subject = "Your OTP code"

  with open("app/templates/otp_email.html") as f:
    template = Template(f.read())
  html_body = template.render(OTP=otp)

  msg = MIMEText(html_body, "html")
  msg["Subject"] = subject
  msg["From"] = sender_email
  msg["To"] = to_email

  try:
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
      server.starttls()
      server.login(sender_email, sender_password)
      server.sendmail(sender_email, to_email, msg.as_string())
    return True
  except Exception as e:
    print(e)
    return False