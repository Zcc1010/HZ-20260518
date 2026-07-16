"""测试定值单下载功能：搜索设备 → 获取详情 → 下载PDF。

用法：
    python scripts/test_setting_download.py 鼎滨4D25线
    python scripts/test_setting_download.py 安庆变5789线 安庆变
"""

import sys
import httpx

BASE_URL = "http://10.34.38.113:8020"
LEDGER_API = f"{BASE_URL}/ledger/equipment/secondary"


def build_download_url(pdf_file_name: str, setting_code: str, setting_type: str) -> str:
    if setting_type == "0":
        if setting_code:
            return f"http://10.138.4.27:8448/ahTransFersysRoot/FileViewServlet?index1={setting_code}&type=2html"
    elif setting_type == "1":
        if pdf_file_name:
            return f"http://10.34.38.113/hddzd/{pdf_file_name}"
    elif setting_type == "2":
        if pdf_file_name:
            return f"http://10.34.38.113/omsdzd/{pdf_file_name}"
    return ""


def main():
    if len(sys.argv) < 2:
        print("用法: python test_setting_download.py <设备名> [厂站名]")
        sys.exit(1)

    device_name = sys.argv[1]
    st_name = sys.argv[2] if len(sys.argv) > 2 else ""

    with httpx.Client(timeout=60) as client:
        # 1. 搜索设备
        candidates = [device_name, device_name.replace(" ", "")]
        if st_name:
            prefixed = f"{st_name}{device_name.replace(' ', '')}"
            if prefixed not in candidates:
                candidates.append(prefixed)

        records = []
        for name in candidates:
            body = {"onceDeviceName": name, "limit": 10, "page": 1}
            if st_name:
                body["stName"] = st_name
            print(f"[1] 搜索设备: {name} ...", end=" ")
            resp = client.post(f"{LEDGER_API}/getPageList", json=body)
            resp.raise_for_status()
            data = resp.json().get("data", {})
            records = data.get("records") or data.get("list") or []
            print(f"找到 {len(records)} 条")
            if records:
                break

        if not records:
            print("未找到设备，退出")
            return

        device = records[0]
        unique_code = device.get("uniqueCode", "")
        actual_name = device.get("onceDeviceName", device_name)
        station = device.get("stName", "")
        print(f"[1] 使用设备: {actual_name} ({station}), uniqueCode={unique_code}")

        # 2. 获取定值单详情
        print(f"[2] 获取定值单详情: uniqueCode={unique_code} ...")
        detail_resp = client.get(f"{LEDGER_API}/getDzDetailByUniqueCode/{unique_code}")
        detail_resp.raise_for_status()
        detail_data = detail_resp.json().get("data", {})

        detail_list = detail_data.get("dingZhiDetail", []) if isinstance(detail_data, dict) else []
        equipment = detail_list[0] if detail_list else (detail_data if isinstance(detail_data, dict) else {})

        pdf_file = detail_data.get("pdfFileName", "") or ""
        setting_code = equipment.get("settingValueCode", "") or ""
        setting_type = str(equipment.get("settingValueType", "") or "")

        print(f"[2] pdfFileName={pdf_file}")
        print(f"[2] settingValueCode={setting_code}")
        print(f"[2] settingValueType={setting_type}")

        # 3. type 0: 尝试 220kV API
        if setting_type == "0" or not setting_type:
            if setting_code:
                pdf_url = f"{BASE_URL}/dingzhi/get220kVSettingBookFilePdfX"
                print(f"[3] type=0, 尝试220kV API: POST {pdf_url} body=[{setting_code}] ...")
                try:
                    pdf_resp = client.post(pdf_url, json=[setting_code], timeout=30)
                    print(f"[3] 响应: status={pdf_resp.status_code}, size={len(pdf_resp.content)} bytes")
                    if pdf_resp.status_code == 200 and len(pdf_resp.content) > 100:
                        out = f"{actual_name}_定值单.pdf"
                        with open(out, "wb") as f:
                            f.write(pdf_resp.content)
                        print(f"[3] 已保存: {out}")
                    else:
                        print(f"[3] 220kV API 返回无效内容")
                        print(f"[3] 响应体前500字: {pdf_resp.text[:500]}")
                except Exception as e:
                    print(f"[3] 220kV API 失败: {e}")
            else:
                print(f"[3] type=0 但无 settingValueCode，无法获取PDF")

        # 4. type 1/2: 直接下载
        elif setting_type in ("1", "2"):
            download_url = build_download_url(pdf_file, setting_code, setting_type)
            if download_url:
                print(f"[4] type={setting_type}, 下载: {download_url} ...")
                try:
                    file_resp = client.get(download_url, follow_redirects=True)
                    file_resp.raise_for_status()
                    print(f"[4] 响应: status={file_resp.status_code}, size={len(file_resp.content)} bytes")
                    print(f"[4] content-type: {file_resp.headers.get('content-type', '')}")
                    if len(file_resp.content) > 100:
                        ext = ".pdf" if "pdf" in file_resp.headers.get("content-type", "") or download_url.endswith(".pdf") else ".bin"
                        out = f"{actual_name}_定值单{ext}"
                        with open(out, "wb") as f:
                            f.write(file_resp.content)
                        print(f"[4] 已保存: {out}")
                    else:
                        print(f"[4] 内容过小或为空")
                        print(f"[4] 响应体前500字: {file_resp.text[:500]}")
                except Exception as e:
                    print(f"[4] 下载失败: {e}")
            else:
                print(f"[4] 无法构造下载URL: pdfFile={pdf_file}, settingCode={setting_code}")
        else:
            print(f"[?] 未知 settingValueType={setting_type}")


if __name__ == "__main__":
    main()
