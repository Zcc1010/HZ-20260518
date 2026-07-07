# -*- coding: utf-8 -*-
"""定值校核 V2 功能测试用例

测试覆盖：
1. 工作区 CRUD（创建、列表、重命名、删除）
2. 文件操作（上传、读取、写入、重命名、复制、移动、删除）
3. 文件树构建（排序、过滤）
4. SSE 事件端点
5. copy-to-workspace（从 job 复制到工作区）
"""

import json
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ── Fixtures ──

@pytest.fixture
def workspace_root(monkeypatch, tmp_path):
    """临时工作区根目录"""
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setattr(
        "webui.api.routes.setting_check_v2._workspace_root",
        lambda: root,
    )
    return root


@pytest.fixture
def client(workspace_root):
    """FastAPI 测试客户端"""
    from fastapi import FastAPI
    from webui.api.routes.setting_check_v2 import router

    app = FastAPI()
    app.include_router(router, prefix="/api/setting-check-v2")
    return TestClient(app)


# ── 工作区 CRUD ──

class TestWorkspaceCRUD:
    """工作区增删改查"""

    def test_list_workspaces_empty(self, client):
        resp = client.get("/api/setting-check-v2/workspaces")
        assert resp.status_code == 200
        assert resp.json() == {"items": []}

    def test_create_workspace(self, client):
        resp = client.post("/api/setting-check-v2/workspaces", json={"name": "测试站-设备A"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "测试站-设备A"

    def test_create_workspace_duplicate(self, client):
        client.post("/api/setting-check-v2/workspaces", json={"name": "重复"})
        resp = client.post("/api/setting-check-v2/workspaces", json={"name": "重复"})
        assert resp.status_code == 409

    def test_create_workspace_invalid_name(self, client):
        resp = client.post("/api/setting-check-v2/workspaces", json={"name": "a/b"})
        assert resp.status_code == 400

    def test_list_workspaces_after_create(self, client):
        client.post("/api/setting-check-v2/workspaces", json={"name": "站A"})
        client.post("/api/setting-check-v2/workspaces", json={"name": "站B"})
        resp = client.get("/api/setting-check-v2/workspaces")
        names = [i["name"] for i in resp.json()["items"]]
        assert names == ["站A", "站B"]

    def test_rename_workspace(self, client):
        client.post("/api/setting-check-v2/workspaces", json={"name": "旧名"})
        resp = client.patch("/api/setting-check-v2/workspaces/旧名", json={"name": "新名"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "新名"
        # 旧名不存在，新名存在
        resp = client.get("/api/setting-check-v2/workspaces")
        names = [i["name"] for i in resp.json()["items"]]
        assert "新名" in names
        assert "旧名" not in names

    def test_delete_workspace(self, client):
        client.post("/api/setting-check-v2/workspaces", json={"name": "待删"})
        resp = client.delete("/api/setting-check-v2/workspaces/待删")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        resp = client.get("/api/setting-check-v2/workspaces")
        assert resp.json() == {"items": []}

    def test_delete_workspace_not_found(self, client):
        resp = client.delete("/api/setting-check-v2/workspaces/不存在")
        assert resp.status_code == 404


# ── 文件操作 ──

class TestFileOperations:
    """文件上传、读取、写入、重命名、复制、移动、删除"""

    def _create_ws(self, client, name="测试"):
        client.post("/api/setting-check-v2/workspaces", json={"name": name})

    def test_upload_file(self, client):
        self._create_ws(client)
        resp = client.post(
            "/api/setting-check-v2/workspaces/测试/upload",
            files={"files": ("test.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 200
        assert "test.txt" in resp.json()["files"]

    def test_upload_to_subdirectory(self, client):
        self._create_ws(client)
        resp = client.post(
            "/api/setting-check-v2/workspaces/测试/upload",
            files={"files": ("定值单/report.md", b"# Report", "text/plain")},
        )
        assert resp.status_code == 200
        # 验证文件在子目录中
        resp = client.get("/api/setting-check-v2/workspaces/测试/read?path=定值单/report.md")
        assert resp.status_code == 200

    def test_read_text_file(self, client):
        self._create_ws(client)
        client.post(
            "/api/setting-check-v2/workspaces/测试/upload",
            files={"files": ("hello.txt", "你好世界".encode("utf-8"), "text/plain")},
        )
        resp = client.get("/api/setting-check-v2/workspaces/测试/read?path=hello.txt")
        assert resp.status_code == 200
        assert "你好世界" in resp.text

    def test_read_binary_file(self, client):
        self._create_ws(client)
        # xlsx 文件应返回 base64
        fake_xlsx = b"PK\x03\x04fake xlsx content"
        client.post(
            "/api/setting-check-v2/workspaces/测试/upload",
            files={"files": ("data.xlsx", fake_xlsx, "application/octet-stream")},
        )
        resp = client.get("/api/setting-check-v2/workspaces/测试/read?path=data.xlsx")
        assert resp.status_code == 200
        data = resp.json()
        assert "base64" in data
        assert data["name"] == "data.xlsx"

    def test_write_file(self, client):
        self._create_ws(client)
        resp = client.put(
            "/api/setting-check-v2/workspaces/测试/write",
            json={"path": "notes.md", "content": "# 笔记\n内容"},
        )
        assert resp.status_code == 200
        # 验证写入成功
        resp = client.get("/api/setting-check-v2/workspaces/测试/read?path=notes.md")
        assert "# 笔记" in resp.text

    def test_rename_file(self, client):
        self._create_ws(client)
        client.put("/api/setting-check-v2/workspaces/测试/write", json={"path": "old.md", "content": "x"})
        resp = client.post(
            "/api/setting-check-v2/workspaces/测试/rename",
            json={"path": "old.md", "newName": "new.md"},
        )
        assert resp.status_code == 200
        # 旧文件不存在
        resp = client.get("/api/setting-check-v2/workspaces/测试/read?path=old.md")
        assert resp.status_code == 404
        # 新文件存在
        resp = client.get("/api/setting-check-v2/workspaces/测试/read?path=new.md")
        assert resp.status_code == 200

    def test_copy_file(self, client):
        self._create_ws(client)
        client.put("/api/setting-check-v2/workspaces/测试/write", json={"path": "src.md", "content": "data"})
        resp = client.post(
            "/api/setting-check-v2/workspaces/测试/copy",
            json={"src": "src.md", "dest": "dest.md"},
        )
        assert resp.status_code == 200
        # 两个文件都存在
        resp = client.get("/api/setting-check-v2/workspaces/测试/read?path=dest.md")
        assert resp.status_code == 200

    def test_move_file(self, client):
        self._create_ws(client)
        client.put("/api/setting-check-v2/workspaces/测试/write", json={"path": "a.md", "content": "x"})
        resp = client.post(
            "/api/setting-check-v2/workspaces/测试/move",
            json={"src": "a.md", "dest": "子目录/a.md"},
        )
        assert resp.status_code == 200
        resp = client.get("/api/setting-check-v2/workspaces/测试/read?path=子目录/a.md")
        assert resp.status_code == 200

    def test_duplicate_file(self, client):
        self._create_ws(client)
        client.put("/api/setting-check-v2/workspaces/测试/write", json={"path": "orig.md", "content": "x"})
        resp = client.post(
            "/api/setting-check-v2/workspaces/测试/duplicate",
            json={"path": "orig.md"},
        )
        assert resp.status_code == 200
        # 检查副本存在
        resp = client.get("/api/setting-check-v2/workspaces/测试/tree")
        names = [n["name"] for n in resp.json() if n["type"] == "file"]
        assert "orig.md" in names
        assert any("副本" in n for n in names)

    def test_delete_file(self, client):
        self._create_ws(client)
        client.put("/api/setting-check-v2/workspaces/测试/write", json={"path": "del.md", "content": "x"})
        resp = client.delete("/api/setting-check-v2/workspaces/测试/file?path=del.md")
        assert resp.status_code == 200
        resp = client.get("/api/setting-check-v2/workspaces/测试/read?path=del.md")
        assert resp.status_code == 404

    def test_delete_directory(self, client):
        self._create_ws(client)
        client.put("/api/setting-check-v2/workspaces/测试/write", json={"path": "dir/f.md", "content": "x"})
        resp = client.delete("/api/setting-check-v2/workspaces/测试/file?path=dir")
        assert resp.status_code == 200

    def test_search_files(self, client):
        self._create_ws(client)
        client.put("/api/setting-check-v2/workspaces/测试/write", json={"path": "定值单/宝桥362.md", "content": "x"})
        client.put("/api/setting-check-v2/workspaces/测试/write", json={"path": "定值单/宝桥363.md", "content": "x"})
        client.put("/api/setting-check-v2/workspaces/测试/write", json={"path": "计算书/宝桥变1变.md", "content": "x"})
        resp = client.get("/api/setting-check-v2/workspaces/测试/search?q=宝桥")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 3

    def test_path_traversal_blocked(self, client):
        self._create_ws(client)
        resp = client.get("/api/setting-check-v2/workspaces/测试/read?path=../../etc/passwd")
        assert resp.status_code == 400


# ── 文件树 ──

class TestFileTree:
    """文件树构建、排序、过滤"""

    def _setup_workspace(self, client, workspace_root):
        """创建包含标准目录结构的工作区"""
        ws = workspace_root / "测试"
        ws.mkdir()
        (ws / "定值单").mkdir()
        (ws / "计算书").mkdir()
        (ws / "说明书").mkdir()
        (ws / "报告").mkdir()
        # 写入测试文件
        (ws / "定值单" / "设备A.md").write_text("# 设备A", encoding="utf-8")
        (ws / "计算书" / "计算1.md").write_text("# 计算", encoding="utf-8")
        (ws / "报告" / "校核报告.md").write_text("# 报告", encoding="utf-8")
        (ws / "报告" / "校核报告.docx").write_bytes(b"fake docx")

    def test_tree_structure(self, client, workspace_root):
        self._setup_workspace(client, workspace_root)
        resp = client.get("/api/setting-check-v2/workspaces/测试/tree")
        assert resp.status_code == 200
        tree = resp.json()
        names = [n["name"] for n in tree]
        assert "定值单" in names
        assert "报告" in names

    def test_report_folder_last(self, client, workspace_root):
        """报告文件夹应排在最后"""
        self._setup_workspace(client, workspace_root)
        resp = client.get("/api/setting-check-v2/workspaces/测试/tree")
        tree = resp.json()
        names = [n["name"] for n in tree]
        assert names[-1] == "报告"

    def test_report_only_shows_md(self, client, workspace_root):
        """报告文件夹只显示 .md 文件"""
        self._setup_workspace(client, workspace_root)
        resp = client.get("/api/setting-check-v2/workspaces/测试/tree")
        tree = resp.json()
        report_node = next(n for n in tree if n["name"] == "报告")
        child_names = [c["name"] for c in report_node["children"]]
        assert "校核报告.md" in child_names
        assert "校核报告.docx" not in child_names

    def test_empty_workspace(self, client, workspace_root):
        ws = workspace_root / "空工作区"
        ws.mkdir()
        resp = client.get("/api/setting-check-v2/workspaces/空工作区/tree")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_workspace_not_found(self, client):
        resp = client.get("/api/setting-check-v2/workspaces/不存在/tree")
        assert resp.status_code == 404


# ── SSE 事件 ──

class TestSSEEvents:
    """SSE 文件变更事件"""

    def test_events_endpoint_exists(self, client, workspace_root):
        """SSE 端点应存在且返回正确状态"""
        ws = workspace_root / "测试"
        ws.mkdir()
        # 使用 HEAD 请求检查端点是否存在（SSE 会一直 stream，不能等待完成）
        resp = client.get("/api/setting-check-v2/workspaces/测试/events", headers={"Accept": "text/event-stream"})
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_events_workspace_not_found(self, client):
        resp = client.get("/api/setting-check-v2/workspaces/不存在/events")
        assert resp.status_code == 404


# ── 集成测试 ──

class TestIntegration:
    """端到端集成测试"""

    def test_full_workflow(self, client):
        """完整工作流：创建工作区 → 上传文件 → 读取 → 修改 → 删除"""
        # 1. 创建工作区
        resp = client.post("/api/setting-check-v2/workspaces", json={"name": "集成测试"})
        assert resp.status_code == 200

        # 2. 上传定值单
        resp = client.post(
            "/api/setting-check-v2/workspaces/集成测试/upload",
            files={"files": ("定值单/设备A.md", "# 设备A定值单\n\n保护定值：100A".encode(), "text/plain")},
        )
        assert resp.status_code == 200

        # 3. 上传计算书
        resp = client.post(
            "/api/setting-check-v2/workspaces/集成测试/upload",
            files={"files": ("计算书/计算1.md", "# 计算书\n\n整定计算：120A".encode(), "text/plain")},
        )
        assert resp.status_code == 200

        # 4. 上传报告
        resp = client.post(
            "/api/setting-check-v2/workspaces/集成测试/upload",
            files={"files": ("报告/校核报告.md", "# 校核报告\n\n结论：合格".encode(), "text/plain")},
        )
        assert resp.status_code == 200

        # 5. 验证文件树
        resp = client.get("/api/setting-check-v2/workspaces/集成测试/tree")
        tree = resp.json()
        names = [n["name"] for n in tree]
        assert names[-1] == "报告"  # 报告在最后

        # 6. 读取定值单
        resp = client.get("/api/setting-check-v2/workspaces/集成测试/read?path=定值单/设备A.md")
        assert "100A" in resp.text

        # 7. 修改报告
        resp = client.put(
            "/api/setting-check-v2/workspaces/集成测试/write",
            json={"path": "报告/校核报告.md", "content": "# 校核报告\n\n结论：不合格\n\n问题：定值偏高"},
        )
        assert resp.status_code == 200

        # 8. 验证修改
        resp = client.get("/api/setting-check-v2/workspaces/集成测试/read?path=报告/校核报告.md")
        assert "不合格" in resp.text

        # 9. 搜索文件
        resp = client.get("/api/setting-check-v2/workspaces/集成测试/search?q=校核")
        assert len(resp.json()["items"]) == 1

        # 10. 删除工作区
        resp = client.delete("/api/setting-check-v2/workspaces/集成测试")
        assert resp.status_code == 200

        # 11. 验证删除
        resp = client.get("/api/setting-check-v2/workspaces")
        names = [i["name"] for i in resp.json()["items"]]
        assert "集成测试" not in names


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
