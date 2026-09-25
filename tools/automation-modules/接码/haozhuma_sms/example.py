from haozhuma_client import HaoZhuMaClient
from constants import ISP, PROVINCES
import time

def main():
    # --- 配置信息 ---
    USERNAME = "API-账号"
    PASSWORD = "API-密码"
    PROJECT_ID = "109258" # 项目ID (sid)
    # ----------------
    
    # 1. 初始化客户端
    client = HaoZhuMaClient(USERNAME, PASSWORD)
    
    # 2. 登录 (内部会自动列出余额)
    if not client.login():
        print("登录失败，请检查账号密码！")
        return

    # 3. 获取号码 (示例：移动，北京)
    # phone = client.get_phone(sid=PROJECT_ID, isp="1", province="11")
    phone = client.get_phone(sid=PROJECT_ID)
    
    if phone:
        print(f"当前操作号码: {phone}")
        
        # 4. 获取验证码 (超时 120 秒，每 15 秒检查一次)
        result = client.get_message(sid=PROJECT_ID, phone=phone, timeout=120)
        
        if result:
            print(f"收到短信原文: {result['sms']}")
            print(f"提取验证码: {result['yzm']}")
            # 5. 成功后释放号码
            client.release_phone(sid=PROJECT_ID, phone=phone)
        else:
            print("长时间未收到短信，正在拉黑号码...")
            # 6. 超时则拉黑（避免再次刷到此号）
            client.add_blacklist(sid=PROJECT_ID, phone=phone)
    else:
        print("暂无可取号码，请稍后再试或检查余额/项目ID。")

if __name__ == "__main__":
    main()
