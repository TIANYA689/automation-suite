import requests
import time
from loguru import logger

class TaxinClient:
    """
    他信接码平台 API 客户端 (api.my531.com)
    """
    def __init__(self, username=None, password=None, dev_name=None):
        self.base_url = "http://api.my531.com"
        self.username = username
        self.password = password
        self.dev_name = dev_name
        self.token = None

    def login(self):
        """登录获取 token"""
        params = {
            "username": self.username,
            "password": self.password,
            "type": "json"
        }
        try:
            res = requests.get(f"{self.base_url}/Login/", params=params).json()
            if res.get("stat"):
                self.token = res["data"]["token"]
                logger.success("登录成功")
                return True
            else:
                logger.error(f"登录失败: {res.get('message')}")
                return False
        except Exception as e:
            logger.exception(f"登录异常: {e}")
            return False

    def get_balance(self):
        """查询余额"""
        if not self.token: return None
        params = {"token": self.token, "type": "json"}
        res = requests.get(f"{self.base_url}/Balance/", params=params).json()
        if res.get("stat"):
            return res["data"]
        return None

    def get_phone(self, project_id, isp=0, card=0, area=None):
        """获取手机号"""
        params = {
            "token": self.token,
            "id": project_id,
            "isp": isp,
            "card": card,
            "type": "json"
        }
        if area: params["area"] = area
        
        res = requests.get(f"{self.base_url}/GetPhone/", params=params).json()
        if res.get("stat"):
            return res["data"]
        else:
            logger.warning(f"获取号码失败: {res.get('message')}")
            return None

    def get_message(self, project_id, phone, timeout=60, interval=5):
        """循环获取验证码"""
        start_time = time.time()
        params = {
            "token": self.token,
            "id": project_id,
            "phone": phone,
            "type": "json"
        }
        if self.dev_name:
            params["dev"] = self.dev_name

        logger.info(f"开始获取验证码 [{phone}]...")
        while time.time() - start_time < timeout:
            res = requests.get(f"{self.base_url}/GetMsg/", params=params).json()
            if res.get("stat"):
                logger.success(f"验证码获取成功: {res['data']}")
                return res["data"]
            
            if "没有收到" not in res.get("message", ""):
                logger.info(f"状态: {res.get('message')}")
                
            time.sleep(interval)
        
        logger.error(f"获取验证码超时")
        return None

    def cancel(self, project_id, phone):
        """释放号码"""
        params = {
            "token": self.token,
            "id": project_id,
            "phone": phone,
            "type": "json"
        }
        res = requests.get(f"{self.base_url}/Cancel/", params=params).json()
        return res.get("stat")

    def add_black(self, project_id, phone):
        """加黑号码"""
        params = {
            "token": self.token,
            "id": project_id,
            "phone": phone,
            "type": "json"
        }
        res = requests.get(f"{self.base_url}/Addblack/", params=params).json()
        return res.get("stat")
