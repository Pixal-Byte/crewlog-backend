# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Nova Nightingale
"""
Small Python script two give to secret keys for hashing IPs and Timing Tokens
Execute the script to get two urlsafe keys
"""
import secrets
ip_token_key = secrets.token_urlsafe(48)
timing_token_key = secrets.token_urlsafe(48)

print("Put these tokens in a .env file:")
print(f"CREWLOG_TOKEN_KEY={timing_token_key}")
print(f"CREWLOG_IP_KEY={ip_token_key}")