"""Save full cookie string to harvester auth state — only .oceanengine.com domain."""
import json
from pathlib import Path

COOKIE_STR = """tt_utm_url=https://yuntu.oceanengine.com/support/content/root?graphId=610&pageId=445&spaceId=221&timestamp=1773837751729; tt_utm=yuntu.oceanengine.com; s_v_web_id=verify_mmw9olsj_70hGGJ7t_uQXq_4Lou_9zqx_YKe9Km2MAuIG; ttwid=1%7CfpCEAJ6mHArTqzOJ5NtdwvE8oUwOsW-7_vZlEJ5DcOU%7C1769344116%7C014ba944a17c875ae8b8702eee04eedcb4ccb921dd98ed99bfe4e364589e8525; passport_csrf_token=ba5a5c91f3506fc5c93cbeae5c03e2ce; passport_csrf_token_default=ba5a5c91f3506fc5c93cbeae5c03e2ce; loginType=mobile; passport_mfa_token=Cjf%2BzS92tT0QL0NdGkBtz7QGvaKemIp%2B9CA16FajLV%2F7xKDRKWsFcOwU%2B2OdXZe4m49leYm0GbPhGkoKPAAAAAAAAAAAAABQMohn%2BLQ%2Fozmb8Wec8dJ8b5NQqYFZls0zC4%2FmCSXGOUG75FqjHV72acsaC9AEUqrumRCWuIwOGPax0WwgAiIBA4arwhc%3D; d_ticket=a97fc4a1b027894d877ad6de1fd91193b7fc9; n_mh=TqyOolUZrShvCL8D5j3TlAZ9KQkcVvPs02rjsUEDX48; sso_auth_status=117f3643878104b25091f6e1eef271ef; sso_auth_status_ss=117f3643878104b25091f6e1eef271ef; sso_uid_tt=58970fad25f2a01ca64ce10fbe5041cb; sso_uid_tt_ss=58970fad25f2a01ca64ce10fbe5041cb; toutiao_sso_user=2ba273ea8d3e1d16167c405f3a9c2a3a; toutiao_sso_user_ss=2ba273ea8d3e1d16167c405f3a9c2a3a; sid_ucp_sso_v1=1.0.0-KDgyYTMwMmM5Y2Y2M2Y5Y2M3NWI4OTgxMjdhNzRhZmVmMDg3Y2FkMDcKHwjAs6CG8838ARCAq-vNBhjkDiAMMLuazKcGOAJA8QcaAmxmIiAyYmEyNzNlYThkM2UxZDE2MTY3YzQwNWYzYTljMmEzYQ; ssid_ucp_sso_v1=1.0.0-KDgyYTMwMmM5Y2Y2M2Y5Y2M3NWI4OTgxMjdhNzRhZmVmMDg3Y2FkMDcKHwjAs6CG8838ARCAq-vNBhjkDiAMMLuazKcGOAJA8QcaAmxmIiAyYmEyNzNlYThkM2UxZDE2MTY3YzQwNWYzYTljMmEzYQ; odin_tt=d24f7eeed8c9e38e701704ccb40efb39979a00ace837ce9625574171c49aff78bfec5ab34105314004d8e098b0d2f192b01a0c5ed12d2049d96b84dbecc77304; passport_auth_status=b15d139d3b22d24f8bd10dfd1b196fce%2C2d79f09300d0c6c3619e0834502c9fda; passport_auth_status_ss=b15d139d3b22d24f8bd10dfd1b196fce%2C2d79f09300d0c6c3619e0834502c9fda; sid_guard=f838dfe443a7c7f705d7215ce3e2d11c%7C1773852033%7C5184001%7CSun%2C+17-May-2026+16%3A40%3A34+GMT; uid_tt=4de9af789eb5949f82876d5136b5aa51; uid_tt_ss=4de9af789eb5949f82876d5136b5aa51; sid_tt=f838dfe443a7c7f705d7215ce3e2d11c; sessionid=f838dfe443a7c7f705d7215ce3e2d11c; sessionid_ss=f838dfe443a7c7f705d7215ce3e2d11c; session_tlb_tag=sttt%7C15%7C-Djf5EOnx_cF1yFc4-LRHP_________0Iwf2nrEsIejBU0eRG1JwKBCbdbfLf1QMeLmUsqBrRmU%3D; is_staff_user=false; sid_ucp_v1=1.0.0-KDliYzNkYzAyNWFlYWZhZGFjMmExMjM2NDU2NjQyZmM3YTY2N2E1NTEKGQjAs6CG8838ARCBq-vNBhjkDiAMOAJA8QcaAmxmIiBmODM4ZGZlNDQzYTdjN2Y3MDVkNzIxNWNlM2UyZDExYw; ssid_ucp_v1=1.0.0-KDliYzNkYzAyNWFlYWZhZGFjMmExMjM2NDU2NjQyZmM3YTY2N2E1NTEKGQjAs6CG8838ARCBq-vNBhjkDiAMOAJA8QcaAmxmIiBmODM4ZGZlNDQzYTdjN2Y3MDVkNzIxNWNlM2UyZDExYw; gd_random=eyJtYXRjaCI6dHJ1ZSwicGVyY2VudCI6MC44MzI0Mzg1MDEzOTUwNzQxfQ==.rsEGwcB0PIZcjyZimMe2sXLDmyu0wosakuvTiF+0vSU=; yuntu_brand_industry-version=10005; csrftoken=f8psPVUck3N31QX_6iPzeH3b; advertiser_id=1805203190148185; tt_scid=TiDfEaDaAZ5VCBfzgKBN5Srkl7y-B2ba519CMgjsslJn9XP8EL-UJIefPERrbVwUd8ff; _tea_utm_cache_1229=undefined; msToken=SiH7VLn5JPPdNyXjxcdhbd9WKPP9kprUAsoeu3ClKV9zEl1fa6Os9idckVhtmGezZgTiNyYj9jeC8-6QZzxz7wM6Fm_9MyFUSqhjVRpRdnIcwq5Axjlvdt0="""

cookies = []
for pair in COOKIE_STR.strip().split("; "):
    eq = pair.find("=")
    if eq < 0:
        continue
    name = pair[:eq].strip()
    value = pair[eq+1:].strip()
    cookies.append({
        "name": name,
        "value": value,
        "domain": ".oceanengine.com",
        "path": "/",
        "httpOnly": True,
        "secure": True,
        "sameSite": "None",
    })

state = {"cookies": cookies, "origins": []}
path = Path("/app/data/harvester_auth.json")
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
print(f"Saved {len(cookies)} cookies to {path}")
