"""临时脚本：实测当前 Qt 定位坐标的 Photon / BigDataCloud 完整返回"""
import json
import urllib.request

coords = [(28.3304, 106.1866), (28.3302, 106.1864)]  # 来自 location_history

for lat, lng in coords:
    print(f"=== 坐标 ({lat}, {lng}) ===")
    # Photon
    try:
        url = f"https://photon.komoot.io/reverse?lon={lng}&lat={lat}"
        req = urllib.request.Request(url, headers={"User-Agent": "BNOS-AI/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        props = (data.get("features") or [{}])[0].get("properties", {})
        print("  Photon properties:", json.dumps(props, ensure_ascii=False))
    except Exception as e:
        print(f"  Photon FAIL: {e}")
    # BigDataCloud
    try:
        url = (f"https://api.bigdatacloud.net/data/reverse-geocode-client"
               f"?latitude={lat}&longitude={lng}&localityLanguage=zh")
        req = urllib.request.Request(url, headers={"User-Agent": "BNOS-AI/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        print("  BigDataCloud:", json.dumps({
            "locality": data.get("locality"), "city": data.get("city"),
            "principalSubdivision": data.get("principalSubdivision"),
            "countryName": data.get("countryName"),
        }, ensure_ascii=False))
    except Exception as e:
        print(f"  BigDataCloud FAIL: {e}")
    print()
