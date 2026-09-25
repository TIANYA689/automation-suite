#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import unittest

from src.receiver_22do_free import MailMessage, Receiver22DoFree, ReceiverError


class Receiver22DoFreeTest(unittest.TestCase):
    def test_build_email_with_known_domain(self):
        client = Receiver22DoFree()
        email = client.build_email(local="abc123", domain="linshiyou.com")
        self.assertEqual(email, "abc123@linshiyou.com")

    def test_build_email_defaults_to_google(self):
        client = Receiver22DoFree()
        email = client.build_email(local="abc123")
        self.assertEqual(email, "abc123@googlemail.com")

    def test_create_email_defaults_to_gmail_generator(self):
        class FakeClient(Receiver22DoFree):
            def _post_json(self, path, payload):
                if path == "/action/mailbox/gmail":
                    return {"status": True, "data": {"email": "demo@gmail.com", "account": "demo", "domain": "gmail.com"}}
                if path == "/action/mailbox/login":
                    return {"status": True, "redirect": "https://22.do/inbox/#/demo@gmail.com"}
                return {}

        mailbox = FakeClient().create_email()
        self.assertEqual(mailbox["email"], "demo@gmail.com")
        self.assertEqual(mailbox["domain"], "gmail.com")

    def test_wait_for_email_requires_message_token(self):
        client = Receiver22DoFree()
        with self.assertRaises(ReceiverError):
            client.wait_for_email("demo@gmail.com", timeout=1, interval=1)

    def test_get_verification_code_reuses_email(self):
        class FakeClient(Receiver22DoFree):
            def wait_for_code(self, email_address, **kwargs):
                return "123456"

        result = FakeClient().get_verification_code(email_address="demo@gmail.com")
        self.assertEqual(result["email"], "demo@gmail.com")
        self.assertEqual(result["code"], "123456")

    def test_decode_cloudflare_email(self):
        # 明文是合成值：原用例用的是从真实抓包里解出来的地址，
        # 那会把一个真实邮箱固化进可提交的源码。编码方式与原值一致
        # （同密钥 0x14），所以这条断言仍然覆盖「首字节为密钥」的解码路径。
        self.assertEqual(
            Receiver22DoFree.decode_cfemail("14777c377071797b54716c75796478713a777b79"),
            "ch#demo@example.com",
        )

    def test_parse_content_page(self):
        raw_html = """
        <html>
          <head><link rel="canonical" href="https://22.do/content/abc123" /></head>
          <body>
            <script>
              let email = "demo@linshiyou.com";
              const data = {viewId: 'view-token'};
            </script>
            <div class="email-detail rounded shadow-lg">
              <h5 class="mb-1">Your login code</h5>
              <span class="con">sender@example.com</span>
            </div>
            <iframe src="https://22.do/view/view-token"></iframe>
          </body>
        </html>
        """
        message = Receiver22DoFree().parse_content_page(raw_html)
        self.assertEqual(message.email, "demo@linshiyou.com")
        self.assertEqual(message.content_id, "abc123")
        self.assertEqual(message.view_id, "view-token")
        self.assertEqual(message.subject, "Your login code")
        self.assertEqual(message.sender, "sender@example.com")

    def test_decode_possible_base64_html(self):
        encoded = "PGRpdj7pq5jpm4bnoIHkuLoxMjM0NTY8L2Rpdj4="
        decoded = Receiver22DoFree._decode_possible_base64_html(encoded)
        self.assertIn("123456", Receiver22DoFree.html_to_text(decoded))

    def test_extract_code(self):
        client = Receiver22DoFree()
        message = MailMessage(subject="登录验证码", text_body="您的验证码是 987654，请勿泄露")
        self.assertEqual(client.extract_code(message), "987654")


if __name__ == "__main__":
    unittest.main()
