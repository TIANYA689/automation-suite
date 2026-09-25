#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@File    : demo.py
@Time    : 2026-02-16
@Desc    : ChacuoMailClient 使用示例

功能演示:
    1. 生成随机邮箱
    2. 查看邮件列表
    3. 等待并提取验证码
"""

import sys
import logging
from chacuo_mail_client import ChacuoMailClient

# 日志配置: 只显示消息内容，不加时间戳前缀
logging.basicConfig(level=logging.INFO, format='%(message)s')


def demo_basic():
    """基础功能演示: 生成邮箱 + 查看邮件列表"""
    print("=" * 60)
    print("📌 Demo 1: 基础功能 — 生成邮箱 + 查看邮件列表")
    print("=" * 60)

    # 创建客户端
    client = ChacuoMailClient()

    # 生成随机邮箱
    email = client.generate_email()
    print(f"\n📧 生成的邮箱: {email}")

    # 获取邮件列表
    data = client.get_emails()
    print(f"👤 用户信息: UID={data['user']['UID']}, 有效期至={data['user']['EXPIRETIME']}")
    print(f"📊 统计: 当前在线={data['stat']['curmail']}, 累计={data['stat']['totalmail']}")
    print(f"📬 邮件数量: {len(data['list'])}")

    if data["list"]:
        for i, mail in enumerate(data["list"]):
            print(f"   [{i+1}] 主题: {mail['SUBJECT']}")
            print(f"       发件人: {mail['FROM']}")
            print(f"       时间: {mail['SENDTIME']}")
    else:
        print("   (收件箱为空)")

    return client


def demo_wait_code():
    """验证码获取演示"""
    print("\n" + "=" * 60)
    print("📌 Demo 2: 一站式获取验证码")
    print("=" * 60)

    client = ChacuoMailClient()
    email = client.generate_email()
    print(f"\n📧 邮箱: {email}")
    print(f"ℹ️  请在目标网站使用此邮箱注册，然后等待验证码...")
    print(f"⏳ 开始轮询等待邮件 (最长 120 秒)...\n")

    # 等待并提取验证码
    code = client.get_verification_code(
        timeout=120,
        interval=8,
        # subject_filter="Verification",  # 可选: 按主题过滤
        # sender_filter="no-reply",       # 可选: 按发件人过滤
    )

    if code:
        print(f"\n🎉 成功获取验证码: {code}")
    else:
        print(f"\n❌ 获取验证码失败 (超时或未匹配)")


def demo_multi_domain():
    """多域名演示"""
    print("\n" + "=" * 60)
    print("📌 Demo 3: 多域名支持")
    print("=" * 60)

    # 使用 027168.com 域名
    client = ChacuoMailClient(domain="027168.com")
    email = client.generate_email()
    print(f"\n📧 027168.com 邮箱: {email}")

    # 切换域名生成新邮箱
    email2 = client.generate_email(domain="chacuo.net")
    print(f"📧 chacuo.net 邮箱: {email2}")


def demo_integration():
    """业务集成示例 (伪代码)"""
    print("\n" + "=" * 60)
    print("📌 Demo 4: 业务脚本集成示例")
    print("=" * 60)

    print("""
    # === 在业务脚本中使用示例 ===

    from chacuo_mail_client import ChacuoMailClient

    def register_with_email():
        # 1. 创建邮箱客户端
        mail = ChacuoMailClient()
        email = mail.generate_email()
        print(f"注册邮箱: {email}")

        # 2. 调用目标网站注册 API
        # resp = requests.post("https://target.com/register", json={
        #     "email": email,
        #     "password": "xxx"
        # })

        # 3. 等待并获取验证码
        code = mail.get_verification_code(
            subject_filter="Verification Code",
            timeout=120,
        )
        if not code:
            print("获取验证码失败")
            return None

        # 4. 提交验证码完成注册
        # resp = requests.post("https://target.com/verify", json={
        #     "email": email,
        #     "code": code
        # })

        return code
    """)


if __name__ == "__main__":
    # 默认运行基础演示
    if len(sys.argv) > 1:
        demo_num = sys.argv[1]
        if demo_num == "1":
            demo_basic()
        elif demo_num == "2":
            demo_wait_code()
        elif demo_num == "3":
            demo_multi_domain()
        elif demo_num == "4":
            demo_integration()
        else:
            print("用法: python demo.py [1|2|3|4]")
    else:
        # 默认只运行基础演示
        demo_basic()
