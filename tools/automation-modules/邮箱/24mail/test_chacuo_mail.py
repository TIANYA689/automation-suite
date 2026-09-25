#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@File    : test_chacuo_mail.py
@Time    : 2026-06-06
@Author  : wuyingzhishang
@Version : 1.0
@Desc    : ChacuoMailClient 测试脚本

使用说明:
    python test_chacuo_mail.py
"""

import logging
import sys
import os

# 添加当前目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from chacuo_mail_client import ChacuoMailClient

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def test_generate_email():
    """测试生成随机邮箱"""
    print("\n" + "=" * 50)
    print("测试 1: 生成随机邮箱")
    print("=" * 50)
    
    client = ChacuoMailClient()
    email = client.generate_email()
    print(f"✅ 生成的邮箱地址: {email}")
    
    return client


def test_custom_email():
    """测试自定义邮箱用户名"""
    print("\n" + "=" * 50)
    print("测试 2: 自定义邮箱用户名")
    print("=" * 50)
    
    client = ChacuoMailClient()
    username = f"test_{os.getpid()}"  # 使用进程 ID 避免冲突
    success = client.set_email(username)
    
    if success:
        print(f"✅ 自定义邮箱设置成功: {client.current_email}")
    else:
        print(f"⚠️ 自定义邮箱可能被占用: {username}@chacuo.net")
    
    return client


def test_check_emails():
    """测试检查邮件列表"""
    print("\n" + "=" * 50)
    print("测试 3: 检查邮件列表")
    print("=" * 50)
    
    client = ChacuoMailClient()
    client.generate_email()
    
    try:
        emails = client.get_emails()
        mail_list = emails.get("list", [])
        
        print(f"📬 当前邮箱: {client.current_email}")
        print(f"📊 邮件数量: {len(mail_list)}")
        
        if mail_list:
            for i, mail in enumerate(mail_list[:5], 1):  # 只显示前 5 封
                print(f"  [{i}] 主题: {mail.get('SUBJECT', '无标题')[:50]}")
                print(f"      发件人: {mail.get('FROM', '未知')[:40]}")
                print(f"      时间: {mail.get('SENDTIME', '未知')}")
                print()
        else:
            print("📭 邮箱为空")
            
    except Exception as e:
        print(f"❌ 获取邮件失败: {e}")
    
    return client


def test_wait_for_code():
    """测试等待验证码（需要手动触发）"""
    print("\n" + "=" * 50)
    print("测试 4: 等待验证码")
    print("=" * 50)
    print("⚠️ 此测试需要你在其他网站使用该邮箱注册")
    print("⚠️ 按 Enter 开始等待，或按 Ctrl+C 跳过")
    
    try:
        input("\n按 Enter 开始等待验证码...")
    except KeyboardInterrupt:
        print("\n⏭️ 跳过验证码测试")
        return None
    
    client = ChacuoMailClient()
    email = client.generate_email()
    
    print(f"\n📧 请使用以下邮箱注册: {email}")
    print("⏳ 等待验证码邮件（最多 120 秒）...")
    
    code = client.get_verification_code(
        timeout=120,
        interval=5,
        subject_filter="Verification",
    )
    
    if code:
        print(f"✅ 获取到验证码: {code}")
    else:
        print("❌ 未获取到验证码")
    
    return client


def main():
    """运行所有测试"""
    print("🚀 ChacuoMailClient 测试脚本")
    print("=" * 50)
    
    # 测试 1: 生成随机邮箱
    client1 = test_generate_email()
    
    # 测试 2: 自定义邮箱
    client2 = test_custom_email()
    
    # 测试 3: 检查邮件
    test_check_emails()
    
    # 测试 4: 等待验证码（可选）
    print("\n" + "=" * 50)
    print("是否运行验证码测试？")
    print("此测试需要你在其他网站使用生成的邮箱注册")
    print("=" * 50)
    
    try:
        choice = input("\n是否继续？(y/n): ").strip().lower()
        if choice == 'y':
            test_wait_for_code()
    except KeyboardInterrupt:
        print("\n\n⏭️ 跳过验证码测试")
    
    print("\n" + "=" * 50)
    print("✅ 测试完成")
    print("=" * 50)


if __name__ == "__main__":
    main()
