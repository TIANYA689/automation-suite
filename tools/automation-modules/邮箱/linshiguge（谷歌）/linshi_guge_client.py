import argparse
import html as html_lib
import logging
import re
import time
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

class LinshiGugeClient:
    """
    Linshiguge.com 临时谷歌邮箱 API 客户端实现 (非官方, 基于网页解析)
    使用标准 requests 会话访问站点并调用邮件 API。
    """
    BASE_URL = "https://www.linshiguge.com"
    GMAIL_REFRESH_PATH = "/mail-api/gmail/refresh"
    GMAIL_NEW_PATH = "/mail-api/gmail/new"
    MESSAGE_DETAIL_PATH = "/mail-api/detail/"

    def __init__(self, proxies=None, timeout=15):
        """
        初始化客户端
        :param proxies: 代理字典
        """
        self.proxies = proxies
        if timeout <= 0:
            raise ValueError("timeout 必须大于 0")
        self.timeout = timeout
        self.session = self._create_session()
        self.email_address = None
        self.gmail_token = None
        self._service_origin = self._origin(self.BASE_URL)

    @staticmethod
    def _origin(url):
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return None
        return f"{parsed.scheme}://{parsed.netloc}"

    @staticmethod
    def _redact_error(error):
        return re.sub(r"([?&]token=)[^&\s'\"]+", r"\1<redacted>", str(error))

    @staticmethod
    def _is_email(value):
        return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value or ""))

    @staticmethod
    def _content_text(content):
        raw = html_lib.unescape(str(content or ""))
        return BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)

    @classmethod
    def build_project_keywords(cls, project):
        """根据项目名生成原词和去分隔变体。"""
        if not project:
            return []
        values = project if isinstance(project, (list, tuple, set)) else str(project).split(",")
        keywords = []
        for value in values:
            normalized = str(value).strip().casefold()
            if not normalized:
                continue
            compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", normalized)
            for candidate in (normalized, compact):
                if len(candidate) >= 2 and candidate not in keywords:
                    keywords.append(candidate)
        return keywords

    @staticmethod
    def _matches_any(value, keywords):
        folded = str(value or "").casefold()
        return any(keyword in folded for keyword in keywords)

    @staticmethod
    def extract_verification_code(content, subject="", sender="", pattern=None):
        """从邮件 HTML/纯文本中提取验证码。"""
        text = LinshiGugeClient._content_text(content)
        contexts = (
            text,
            f"{str(subject or '')} {text}",
            f"{str(sender or '')} {text}",
        )
        if pattern:
            for context in contexts:
                match = re.search(pattern, context, flags=re.IGNORECASE)
                if match:
                    return match.group(1) if match.lastindex else match.group(0)

        semantic_patterns = (
            r"(?:验证码|校验码|验证代码|动态码|一次性密码|安全码|verification\s*code|security\s*code|one[- ]?time\s*password|otp|passcode)(?:\s+(?:is|为|是))?\s*[:：]?\s*([A-Z0-9]{4,8})(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9])([A-Z0-9]{4,8})(?![A-Za-z0-9])[^A-Za-z0-9]{0,24}(?:验证码|校验码|verification\s*code|security\s*code|otp)",
        )
        spaced_digit_pattern = (
            r"(?:验证码|校验码|验证代码|动态码|一次性密码|安全码|"
            r"verification\s*code|security\s*code|one[- ]?time\s*password|otp|passcode)"
            r"(?:\s+(?:is|为|是))?\s*[:：]?\s*((?:\d[\s-]+){3,7}\d)"
        )
        for context in contexts:
            spaced_match = re.search(spaced_digit_pattern, context, flags=re.IGNORECASE)
            if spaced_match:
                candidate = re.sub(r"\D", "", spaced_match.group(1))
                if 4 <= len(candidate) <= 8:
                    return candidate
            for candidate_pattern in semantic_patterns:
                match = re.search(candidate_pattern, context, flags=re.IGNORECASE)
                if match:
                    candidate = match.group(1).upper()
                    if candidate.isdigit() or any(char.isdigit() for char in candidate):
                        return candidate

        for candidate in re.findall(r"(?<![A-Za-z0-9])\d{4,8}(?![A-Za-z0-9])", text):
            if len(candidate) == 4 and 1900 <= int(candidate) <= 2099:
                continue
            return candidate
        return None

    def _create_session(self):
        """创建与 mail_tm 模块一致的标准 requests 会话。"""
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/144.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        if self.proxies:
            session.proxies.update(self.proxies)
        return session

    def _request(self, method, url, **kwargs):
        """统一网络请求入口，风格与 mail_tm 模块保持一致。"""
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Accept", "application/json")
        kwargs["headers"] = headers
        kwargs.setdefault("timeout", self.timeout)
        try:
            return self.session.request(method, url, **kwargs)
        except requests.exceptions.RequestException as error:
            logger.error("请求 %s 失败: %s", url, self._redact_error(error))
            return None

    def _remember_response_origin(self, response):
        response_origin = self._origin(getattr(response, "url", ""))
        if response_origin:
            self._service_origin = response_origin

    def _internal_url(self, value):
        """只允许访问初始站点或当前重定向站点，避免详情 URL 越界。"""
        resolved = urljoin(self._service_origin + "/", value)
        origin = self._origin(resolved)
        allowed = {self._origin(self.BASE_URL), self._service_origin}
        if origin not in allowed:
            raise ValueError("拒绝访问非本站 URL")
        return resolved

    def _request_json(self, method, path, **kwargs):
        url = self._internal_url(path)
        headers = {"Accept": "application/json"}
        headers.update(kwargs.pop("headers", {}))
        response = self._request(method, url, headers=headers, **kwargs)
        if response is None:
            return None
        self._remember_response_origin(response)
        if response.status_code != 200:
            logger.error("API 请求失败，状态码: %s", response.status_code)
            return None
        try:
            data = response.json()
        except (TypeError, ValueError):
            logger.error("API 返回的不是有效 JSON")
            return None
        if not isinstance(data, dict):
            logger.error("API 返回结构异常")
            return None
        if data.get("error"):
            logger.error("API 返回错误: %s", data["error"])
            return None
        return data

    def _get_page_html(self, url):
        """获取页面 HTML"""
        response = self._request("GET", url)
        if response is None:
            return None
        self._remember_response_origin(response)
        if response.status_code == 200:
            return response.text
        logger.error("请求失败，状态码: %s", response.status_code)
        return None

    def close(self):
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def get_email(self):
        """
        1. 获取随机分配的临时谷歌邮箱地址
        """
        logger.info("正在获取 linshiguge.com 临时邮箱...")
        page_urls = (
            self.BASE_URL + "/",
            "https://www.haoweichi.com/mail?gmail",
        )
        html = None
        for page_url in page_urls:
            html = self._get_page_html(page_url)
            if html:
                break
        if not html:
            logger.error("入口均不可用，可能触发站点限频 (HTTP 429)")
            return None
        
        soup = BeautifulSoup(html, 'html.parser')
        page = soup.select_one('.mail-page-wrap, .mail-page')

        # 2026 版页面通过 data 属性和 mail-gmail-input 暴露 Gmail 地址。
        address = page.get('data-gmail-alias') if page else None
        gmail_input = soup.select_one('input.mail-gmail-input')
        if not address and gmail_input:
            address = gmail_input.get('value')
        if page:
            self.gmail_token = page.get('data-gmail-token') or self.gmail_token

        # 兼容旧版页面。
        if not address:
            legacy_input = soup.find('input', id='active-mail')
            address = legacy_input.get('value') if legacy_input else None

        address = (address or '').strip()
        if self._is_email(address) and '请稍后' not in address:
            self.email_address = address
            logger.info("成功获取邮箱: %s", self.email_address)
            return self.email_address

        logger.error("未能从页面解析出邮箱地址，页面结构可能已经变化。")
        return None

    def get_api_address(self, params=None):
        """调用 haoweichi v1 地址 API，返回普通临时地址。"""
        data = self._request_json("GET", "/v1/mail/address", params=params or {})
        if not data or data.get("success") is not True:
            return None
        address_data = data.get("data")
        if not isinstance(address_data, dict):
            return None
        address = str(address_data.get("address") or "").strip()
        return address if self._is_email(address) else None

    def change_email(self, mail_type=1):
        """
        切换邮箱地址
        :param mail_type: 1=(.)@gmail.com, 2=(+)@gmail.com, 3=@googlemail.com
        """
        if mail_type not in (1, 2, 3):
            raise ValueError("mail_type 只能是 1、2 或 3")

        logger.info("正在申请更换邮箱地址 (类型: %s)...", mail_type)

        # 新版接口统一生成 Gmail alias，服务端不再接受旧 type 参数。
        if self.gmail_token:
            data = self._request_json("POST", self.GMAIL_NEW_PATH)
            if not data:
                return None
            new_mail = (data.get("address") or '').strip()
            if not self._is_email(new_mail):
                logger.error("新版接口未返回有效邮箱地址")
                return None
            self.gmail_token = data.get("gmailToken") or self.gmail_token
            self.email_address = new_mail
            logger.info("更换成功，新邮箱: %s", self.email_address)
            return self.email_address

        # 兼容旧版接口。
        url = self._internal_url("/index/index/change.html")
        response = self._request("POST", url, data={"type": mail_type})
        if response is None or response.status_code != 200:
            return None
        new_mail = response.text.strip()
        if new_mail == "1":
            logger.warning("访问太频繁，请稍后再试！")
            return None
        if self._is_email(new_mail):
            self.email_address = new_mail
            logger.info("更换成功，新邮箱: %s", self.email_address)
            return self.email_address
        return None

    def get_messages(self):
        """
        2. 获取当前收件箱的邮件列表
        :return: 包含邮件 meta 信息的列表 [{id, sender, subject, time, link}]
        """
        if self.gmail_token:
            return self._get_api_messages()
        return self._get_legacy_messages()

    def _get_api_messages(self):
        data = self._request_json(
            "GET",
            self.GMAIL_REFRESH_PATH,
            params={"token": self.gmail_token},
        )
        if not data:
            return []

        self.gmail_token = data.get("gmailToken") or self.gmail_token
        raw_messages = data.get("emails", [])
        if not isinstance(raw_messages, list):
            logger.error("邮件列表字段不是数组")
            return []

        messages = []
        for item in raw_messages:
            if not isinstance(item, dict) or not item.get("id"):
                logger.warning("跳过缺少有效 ID 的邮件条目")
                continue
            message_id = str(item["id"])
            messages.append({
                "id": message_id,
                "sender": item.get("from") or item.get("email") or "",
                "subject": item.get("subject") or "",
                "time": item.get("time") or str(item.get("time_unix") or ""),
                "time_unix": item.get("time_unix"),
                "link": self._internal_url(
                    self.MESSAGE_DETAIL_PATH + quote(message_id, safe="")
                ),
            })
        return messages

    def _get_legacy_messages(self):
        html = self._get_page_html(self._service_origin + "/")
        if not html:
            return []
            
        soup = BeautifulSoup(html, 'html.parser')
        tbody = soup.find('tbody', id='message-list')
        if not tbody:
            return []
            
        messages = []
        for tr in tbody.find_all('tr'):
            tds = tr.find_all('td')
            # 过滤掉 "正在接收邮件" 和 广告 占位行 (如果只有一列则排除，有效邮件有3列)
            if len(tds) == 3:
                sender = tds[0].get_text(strip=True)
                subject_td = tds[1]
                a_tag = subject_td.find('a')
                if a_tag:
                    subject = a_tag.get_text(strip=True)
                    link = a_tag.get('href')
                    
                    # 排除 loading 行
                    if "正在接收邮件" in sender or "Receiving mails" in sender:
                        continue
                        
                    if not link or '/id/' not in link:
                        logger.warning("跳过缺少有效详情链接的邮件条目")
                        continue
                    msg_id = link.rsplit('/id/', 1)[-1].removesuffix('.html')
                    time_val = tds[2].get_text(strip=True)
                    
                    messages.append({
                        'id': msg_id,
                        'sender': sender,
                        'subject': subject,
                        'time': time_val,
                        'link': self._internal_url(link)
                    })
        return messages

    def get_message_detail(self, message_link):
        """
        3. 获取邮件详细内容
        :param message_link: 邮件的详情页 URL
        :return: 邮件正文 (文本或HTML)
        """
        message_url = self._internal_url(message_link)
        logger.info("正在读取邮件内容: %s", message_url)

        if urlparse(message_url).path.startswith(self.MESSAGE_DETAIL_PATH):
            data = self._request_json("GET", message_url)
            if not data:
                return None
            content = data.get("content")
            return content if content is not None else "无法解析内容"

        html = self._get_page_html(message_url)
        if not html:
            return None
            
        soup = BeautifulSoup(html, 'html.parser')
        
        # 根据 linshiguge 详情页结构提取正文
        # 观察详情页的特征，通常包裹在一个 class 为 "content" 或 panel-body 内
        content_div = soup.find('div', class_='panel-body')
        if content_div:
            return content_div.get_text(separator='\n', strip=True)
            
        # 兜底：返回整个主要区域文本
        main_div = soup.find('section', id='main')
        if main_div:
            return main_div.get_text(separator='\n', strip=True)
            
        return "无法解析内容"

    def wait_for_email(self, timeout=120, interval=10, keyword=None):
        """
        4. 封装轮询方法：等待满足条件的邮件到来
        :param timeout: 最大超时时间(秒)
        :param interval: 每次轮询间隔(秒)
        :param keyword: 可选，限制发件人或标题所包含的关键词
        :return: 找到则返回邮件对象字典（包含其正文 detail），超时返回 None
        """
        if timeout <= 0:
            raise ValueError("timeout 必须大于 0")
        if interval <= 0:
            raise ValueError("interval 必须大于 0")

        logger.info("开始轮询新邮件 (最大等待 %ss，间隔 %ss)...", timeout, interval)
        deadline = time.monotonic() + timeout
        seen_ids = set()
        normalized_keyword = keyword.casefold() if keyword else None

        while time.monotonic() < deadline:
            msgs = self.get_messages()
            for msg in msgs:
                if msg['id'] in seen_ids:
                    continue
                seen_ids.add(msg['id'])
                
                if normalized_keyword:
                    haystack = f"{msg['subject']}\n{msg['sender']}".casefold()
                    if normalized_keyword not in haystack:
                        continue
                        
                logger.info(f"收到新邮件！发件人: {msg['sender']}, 主题: {msg['subject']}")
                # 获取正文内容
                msg['detail'] = self.get_message_detail(msg['link'])
                return msg
                
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(interval, remaining))
            
        logger.warning("等待邮件超时！")
        return None

    def wait_for_verification_code(
        self,
        timeout=120,
        interval=10,
        keyword=None,
        pattern=None,
        subject_keyword=None,
        sender_keyword=None,
        content_keyword=None,
        project=None,
    ):
        """轮询并返回首封可提取验证码的邮件。"""
        if timeout <= 0:
            raise ValueError("timeout 必须大于 0")
        if interval <= 0:
            raise ValueError("interval 必须大于 0")

        deadline = time.monotonic() + timeout
        seen_ids = set()
        normalized_keyword = keyword.casefold() if keyword else None
        normalized_subject = subject_keyword.casefold() if subject_keyword else None
        normalized_sender = sender_keyword.casefold() if sender_keyword else None
        normalized_content = content_keyword.casefold() if content_keyword else None
        project_keywords = self.build_project_keywords(project)
        if not any((
            normalized_keyword,
            normalized_subject,
            normalized_sender,
            normalized_content,
            project_keywords,
        )):
            raise ValueError("至少设置 project 或 keyword/subject/sender/content 过滤条件")
        logger.info("开始等待验证码 (最大等待 %ss，间隔 %ss)...", timeout, interval)
        while time.monotonic() < deadline:
            for message in self.get_messages():
                message_id = message.get("id")
                if not message_id or message_id in seen_ids:
                    continue
                seen_ids.add(message_id)
                subject = str(message.get("subject", ""))
                sender = str(message.get("sender", ""))
                if normalized_subject and normalized_subject not in subject.casefold():
                    continue
                if normalized_sender and normalized_sender not in sender.casefold():
                    continue
                detail = self.get_message_detail(message["link"])
                content_text = self._content_text(detail)
                combined = f"{subject}\n{sender}\n{content_text}".casefold()
                if normalized_keyword and normalized_keyword not in combined:
                    continue
                if normalized_content and normalized_content not in content_text.casefold():
                    continue
                if project_keywords and not self._matches_any(combined, project_keywords):
                    continue
                code = self.extract_verification_code(
                    detail, message.get("subject"), message.get("sender"), pattern
                )
                if code:
                    message["detail"] = detail
                    message["verification_code"] = code
                    logger.info("已提取验证码: %s", code)
                    return message
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(interval, remaining))
        logger.warning("等待验证码超时！")
        return None


def build_parser():
    parser = argparse.ArgumentParser(description="linshiguge 临时 Gmail 客户端")
    parser.add_argument("--probe", action="store_true", help="只获取地址和当前邮件列表，不轮询")
    parser.add_argument("--wait-timeout", type=float, default=120, help="轮询总超时秒数")
    parser.add_argument("--interval", type=float, default=10, help="轮询间隔秒数")
    parser.add_argument("--keyword", help="按主题、发件人或正文过滤，不区分大小写")
    parser.add_argument("--subject-keyword", help="只按主题过滤，不区分大小写")
    parser.add_argument("--sender-keyword", help="只按发件人过滤，不区分大小写")
    parser.add_argument("--content-keyword", help="只按正文过滤，不区分大小写")
    parser.add_argument("--project", help="项目名，自动生成主题/发件人/正文关键词；逗号分隔多个")
    parser.add_argument("--code-pattern", help="自定义验证码正则；有捕获组时返回第 1 组")
    parser.add_argument("--show-body", action="store_true", help="同时输出完整邮件正文")
    parser.add_argument("--change-type", type=int, choices=(1, 2, 3), help="获取地址后更换一次邮箱")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    filters = (
        args.keyword,
        args.subject_keyword,
        args.sender_keyword,
        args.content_keyword,
        args.project,
    )
    if not args.probe and not any(filters):
        logging.error(
            "请设置 --project，或设置 --keyword/--subject-keyword/"
            "--sender-keyword/--content-keyword，避免从无关邮件提取验证码。"
        )
        return 2
    with LinshiGugeClient() as client:
        email = client.get_email()
        if not email:
            logging.error("无法获取临时邮箱，退出。")
            return 1

        if args.change_type:
            email = client.change_email(args.change_type)
            if not email:
                logging.error("更换邮箱失败，退出。")
                return 1

        logging.info("临时谷歌邮箱: %s", email)
        if args.probe:
            messages = client.get_messages()
            logging.info("当前邮件数: %s", len(messages))
            return 0

        email_msg = client.wait_for_verification_code(
            timeout=args.wait_timeout,
            interval=args.interval,
            keyword=args.keyword,
            pattern=args.code_pattern,
            subject_keyword=args.subject_keyword,
            sender_keyword=args.sender_keyword,
            content_keyword=args.content_keyword,
            project=args.project,
        )
        if not email_msg:
            logging.info("超时未提取到验证码。")
            return 2

        print(email_msg["verification_code"])
        if args.show_body:
            print("======== 邮件正文 ========")
            print(email_msg.get("detail", "无正文"))
            print("==========================")
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
