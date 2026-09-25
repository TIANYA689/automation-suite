import requests
import time
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class HaoZhuMaClient:
    """
    豪猪平台 (HaoZhuMa) 手机号接码客户端
    文档地址: https://www.showdoc.com.cn/haozhuma/
    """
    
    def __init__(self, username, password, server_url="https://api.haozhuma.com"):
        self.username = username
        self.password = password
        self.base_url = server_url.rstrip('/') + "/sms/"
        self.token = None
        self.balance = 0.0

    def _request(self, api_action, params=None):
        """通用请求处理"""
        if params is None:
            params = {}
        
        params['api'] = api_action
        if self.token and api_action != 'login':
            params['token'] = self.token
            
        try:
            # 豪猪 API 支持 GET/POST，这里统一使用 GET 传参
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # 部分接口返回的是字符串形式的错误，根据文档 code="0" 为成功
            if str(data.get('code')) != "0" and str(data.get('code')) != "200":
                logger.error(f"API Error [{api_action}]: {data.get('msg')}")
                
            return data
        except Exception as e:
            logger.error(f"Request Error [{api_action}]: {str(e)}")
            return {"code": "-1", "msg": str(e)}

    def login(self):
        """登录并获取 token 及余额"""
        params = {
            "user": self.username,
            "pass": self.password
        }
        res = self._request("login", params)
        if str(res.get('code')) == "0":
            self.token = res.get('token')
            # 脱敏显示 Token (显示前8位和后8位)
            masked_token = f"{self.token[:8]}...{self.token[-8:]}" if self.token else "None"
            logger.info(f"登录成功! Token: {masked_token}")
            # 登录成功后直接列出余额
            self.get_account_info()
            return True
        return False

    def get_account_info(self):
        """获取账号信息（余额）"""
        res = self._request("getSummary")
        if str(res.get('code')) == "0":
            # 根据文档，余额可能在不同字段中返回，通常是 money 或 balance
            # 这里尝试获取常见字段
            self.balance = res.get('money', 0.0)
            logger.info(f"账号余额: {self.balance} 元")
            return res
        return None

    def get_phone(self, sid, isp=None, province=None, ascription=None, author=None):
        """
        获取号码
        :param sid: 项目ID
        :param isp: 运营商 (1:移动, 5:联通, 9:电信...)
        :param province: 省份代码
        :param ascription: 1:虚拟卡, 2:实卡
        :param author: 开发者账号（用于返利）
        """
        params = {"sid": sid}
        if isp: params['isp'] = isp
        if province: params['Province'] = province
        if ascription: params['ascription'] = ascription
        if author: params['author'] = author
        
        res = self._request("getPhone", params)
        if str(res.get('code')) == "0":
            phone = res.get('phone')
            logger.info(f"成功获取号码: {phone} (所属地: {res.get('phone_gsd')})")
            return phone
        return None

    def get_message(self, sid, phone, timeout=120, interval=15):
        """
        获取验证码（循环等待）
        :param sid: 项目ID
        :param phone: 手机号
        :param timeout: 超时时间（秒）
        :param interval: 检查间隔（秒）
        """
        params = {"sid": sid, "phone": phone}
        start_time = time.time()
        
        logger.info(f"开始等待验证码 [{phone}]...")
        while time.time() - start_time < timeout:
            res = self._request("getMessage", params)
            if str(res.get('code')) == "0":
                sms = res.get('sms')
                yzm = res.get('yzm')
                logger.info(f"验证码获取成功: {yzm}")
                return {"sms": sms, "yzm": yzm}
            
            # 等待间隔
            time.sleep(interval)
            
        logger.warning(f"获取验证码超时 [{phone}]")
        return None

    def release_phone(self, sid, phone):
        """释放指定号码"""
        params = {"sid": sid, "phone": phone}
        res = self._request("cancelRecv", params)
        if str(res.get('code')) == "0":
            logger.info(f"号码已释放: {phone}")
            return True
        return False

    def release_all_phones(self):
        """释放所有号码"""
        res = self._request("cancelAllRecv")
        if str(res.get('code')) == "200" or str(res.get('code')) == "0":
            logger.info("所有已订购号码已释放")
            return True
        return False

    def add_blacklist(self, sid, phone):
        """拉黑号码（不接收此号多条短信时使用）"""
        params = {"sid": sid, "phone": phone}
        res = self._request("addBlacklist", params)
        if str(res.get('code')) == "0":
            logger.info(f"号码已拉黑: {phone}")
            return True
        return False
