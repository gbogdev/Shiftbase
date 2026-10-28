from django.core.mail.backends.base import BaseEmailBackend


class FailingBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        raise ConnectionError("smtp down")
