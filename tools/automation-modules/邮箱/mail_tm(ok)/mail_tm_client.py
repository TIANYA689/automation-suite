import requests
import time
import string
import secrets
import logging

logger = logging.getLogger(__name__)

class MailTmClient:
    """
    mail.tm 临时邮箱 API 客户端实现
    官网文档: https://docs.mail.tm/
    """
    BASE_URL = "https://api.mail.tm"

    def __init__(self, proxies=None, timeout=15):
        """
        初始化客户端
        :param proxies: 代理字典，例如: {"http": "http://127.0.0.1:10809", "https": "http://127.0.0.1:10809"}
        """
        if timeout <= 0:
            raise ValueError("timeout 必须大于 0")
        self.session = requests.Session()
        if proxies:
            self.session.proxies.update(proxies)
        self.token = None
        self.account_id = None
        self.address = None
        self.timeout = timeout

    def _request(self, method, endpoint, **kwargs):
        """
        内部统一网络请求方法
        """
        url = f"{self.BASE_URL}{endpoint}"
        
        headers = dict(kwargs.get('headers') or {})
        headers.setdefault('Accept', 'application/json')
        if self.token:
            headers['Authorization'] = f"Bearer {self.token}"
        kwargs['headers'] = headers

        try:
            response = self.session.request(method, url, timeout=self.timeout, **kwargs)
            response.raise_for_status()
            # mail.tm 返回 204 No Content 时可能没有 JSON
            if response.status_code == 204:
                return True
            return response.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            logger.error(f"请求 {url} 失败: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"错误详情: {e.response.text[:200]}")
            return None

    def get_domains(self):
        """
        1. 获取所有可用的后缀域名
        :return: 域名列表字典
        """
        logger.info("正在获取可用域名列表...")
        data = self._request("GET", "/domains")
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and 'hydra:member' in data:
            return data['hydra:member']
        return []

    def create_account(self, address, password):
        """
        2. 注册邮箱账号
        :param address: 完整的邮箱地址，例如: test@example.com
        :param password: 密码
        :return: 账户信息字典
        """
        logger.info(f"正在创建账号: {address}")
        payload = {
            "address": address,
            "password": password
        }
        data = self._request("POST", "/accounts", json=payload)
        if data and 'id' in data:
            logger.info(f"账号创建成功！账户ID: {data['id']}")
            self.account_id = data['id']
            self.address = address
            return data
        return None

    def get_token(self, address, password):
        """
        3. 获取账号的 JWT Token (必须获取 token 后才能接收邮件)
        :param address: 邮箱地址
        :param password: 密码
        :return: Token字符串
        """
        logger.info(f"正在获取账号 Token: {address}")
        payload = {
            "address": address,
            "password": password
        }
        data = self._request("POST", "/token", json=payload)
        if data and 'token' in data:
            self.token = data['token']
            if 'id' in data:
                self.account_id = data['id']
            logger.info("Token 获取成功，已保存至实例中。")
            return self.token
        return None

    def get_messages(self, page=1):
        """
        4. 获取当前账号的邮件列表
        :param page: 页码
        :return: 邮件列表
        """
        logger.info(f"正在拉取邮件列表(第{page}页)...")
        if not self.token:
            logger.warning("尚未获取 Token，无法拉取邮件！")
            return []
        
        data = self._request("GET", f"/messages?page={page}")
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and 'hydra:member' in data:
            return data['hydra:member']
        return []

    def get_message(self, message_id):
        """
        5. 获取指定邮件的详细内容 (正文/附件等)
        :param message_id: 邮件对象的 id
        :return: 邮件详情数据字典
        """
        logger.info(f"正在获取邮件详细内容 (ID: {message_id})...")
        if not self.token:
            return None
        return self._request("GET", f"/messages/{message_id}")

    def delete_message(self, message_id):
        """
        删除邮件
        :param message_id: 邮件对象的 id
        :return: bool 是否成功
        """
        logger.info(f"正在删除邮件 (ID: {message_id})...")
        if not self.token:
            return False
        result = self._request("DELETE", f"/messages/{message_id}")
        return result is not None and result is not False

    def wait_for_email(self, timeout=120, interval=5, keyword=None):
        """
        封装轮询方法：等待满足条件的邮件到来
        :param timeout: 最大超时时间(秒)
        :param interval: 每次轮询间隔(秒)
        :param keyword: 可选，限制发件人或标题所包含的关键词
        :return: 返回符合条件的邮件详情，超时则返回 None
        """
        logger.info(f"开始轮询新邮件 (最大等待 {timeout}s)...")
        start_time = time.monotonic()
        seen_msg_ids = set()

        while time.monotonic() - start_time < timeout:
            msgs = self.get_messages()
            for msg in msgs:
                msg_id = msg.get('id')
                if msg_id in seen_msg_ids:
                    continue
                seen_msg_ids.add(msg_id)
                
                subject = msg.get('subject', '')
                from_addr = msg.get('from', {}).get('address', '')
                
                # 如果有关键字过滤条件
                if keyword:
                    if keyword not in subject and keyword not in from_addr:
                        continue
                
                logger.info(f"收到新邮件！发件人: {from_addr}, 标题: {subject}")
                # 拉取详细内容（例如含有文本正文）
                detail = self.get_message(msg_id)
                return detail
                
            time.sleep(interval)
            
        logger.warning("等待邮件超时！")
        return None

def generate_random_string(length=10):
    """生成随机字符串用于用户名或密码"""
    letters = string.ascii_lowercase + string.digits
    return ''.join(secrets.choice(letters) for _ in range(length))

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    # ================================
    # 使用实列: 自动化创建一个新邮箱并等验证码
    # ================================
    client = MailTmClient()
    
    # 1. 获取一个可用的域名
    domains = client.get_domains()
    if not domains:
        logger.error("无法获取可用域名，退出。")
        raise SystemExit(1)
        
    domain = domains[0]['domain']
    logger.info(f"使用域名: {domain}")
    
    # 2. 随机生成用户名和密码
    username = generate_random_string(8)
    password = generate_random_string(12)
    address = f"{username}@{domain}"
    
    # 3. 创建账号
    account_info = client.create_account(address, password)
    if not account_info:
        raise SystemExit(1)
        
    # 4. 获取登录 Token
    token = client.get_token(address, password)
    if not token:
        raise SystemExit(1)
        
    logger.info("============ 测试账号准备完毕 ============")
    logger.info(f"邮箱地址: {address}")
    logger.info("请尝试向该邮箱发送一封测试邮件，程序正在监听中...")
    logger.info("==========================================")
    
    # 5. 等待接收邮件 (最长等待120秒，无关键词过滤)
    email_detail = client.wait_for_email(timeout=120, interval=5)
    
    if email_detail:
        logger.info("成功拉取到邮件详情内容：")
        print("======== 邮件正文 ========")
        print(email_detail.get('text', '无纯文本正文'))
        print("==========================")
        
        # 测试阅后即焚（删除）
        client.delete_message(email_detail['id'])
        logger.info("流程测试结束，成功！")
