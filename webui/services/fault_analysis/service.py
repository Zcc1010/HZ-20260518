# -*- coding: utf-8 -*-
"""电网故障智能分析服务"""
from __future__ import annotations

import asyncio
import shutil
import uuid
import zipfile
import io
from pathlib import Path

from fastapi import UploadFile

from webui.api.files import generate_download_token
from webui.services.agentplayground.db import connect, utcnow_iso

APP_ID_FAULT_ANALYSIS = "fault-analysis"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    created_by TEXT,
    error_message TEXT,
    station TEXT,
    device TEXT,
    device_type TEXT,
    voltage_level TEXT,
    folder_path TEXT,
    result_file_name TEXT,
    result_relative_path TEXT,
    result_download_token TEXT UNIQUE,
    result_mime_type TEXT,
    result_file_size INTEGER,
    progress INTEGER DEFAULT 0,
    progress_message TEXT,
    evaluation TEXT,
    external_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_fault_jobs_created_at
    ON jobs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_fault_jobs_status_created_at
    ON jobs (status, created_at);
"""


class FaultAnalysisService:
    """电网故障智能分析服务"""

    def __init__(self, app_root: Path):
        self.app_root = app_root
        self.jobs_dir = app_root / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = app_root / "fault_analysis.db"
        self._initialized = False

    def initialize(self):
        if self._initialized:
            return
        with connect(self._db_path) as conn:
            conn.executescript(_SCHEMA)
            # Migration: add external_id column if missing
            try:
                conn.execute("ALTER TABLE jobs ADD COLUMN external_id TEXT")
            except Exception:
                pass  # column already exists
            # Create index after column is guaranteed to exist
            conn.execute("CREATE INDEX IF NOT EXISTS idx_fault_jobs_external_id ON jobs (external_id)")
        self._initialized = True

    @property
    def chunked_upload(self):
        if not hasattr(self, "_chunked_upload"):
            from webui.services.wave_record_parser.service import ChunkedUploadManager
            self._chunked_upload = ChunkedUploadManager(self.app_root)
        return self._chunked_upload

    @property
    def db_path(self):
        return self._db_path

    def _schedule_queue(self):
        pass

    def _conn(self):
        return connect(self._db_path)

    def list_jobs(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_job(self, job_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def create_job(
        self,
        files: list[UploadFile],
        station: str,
        device: str,
        device_type: str = "线路",
        voltage_level: str = "110kV",
        external_id: str = "",
    ) -> dict:
        job_id = uuid.uuid4().hex[:12]
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        # 保存上传的文件
        input_dir = job_dir / "input"
        input_dir.mkdir(exist_ok=True)
        saved_files = []
        for file in files:
            file_path = input_dir / file.filename
            with open(file_path, "wb") as f:
                shutil.copyfileobj(file.file, f)
            saved_files.append(file.filename)

        now = utcnow_iso()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO jobs (id, status, created_at, updated_at, station, device, device_type, voltage_level, folder_path, external_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (job_id, "processing", now, now, station, device, device_type, voltage_level, str(input_dir), external_id or None),
            )

        # 启动后台分析任务
        asyncio.create_task(self._run_analysis(job_id, input_dir, device_type, voltage_level))

        return self.get_job(job_id)

    async def create_job_from_chunked_upload(
        self,
        upload_id: str,
        station: str = "",
        device: str = "",
        device_type: str = "线路",
        voltage_level: str = "110kV",
        external_id: str = "",
    ) -> dict:
        """从分块上传创建任务。"""
        assembled_path = self.chunked_upload.assemble_file(upload_id)

        job_id = uuid.uuid4().hex[:12]
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        input_dir = job_dir / "input"
        input_dir.mkdir(exist_ok=True)

        # 移动组装好的文件到 input 目录
        dest = input_dir / assembled_path.name
        shutil.move(str(assembled_path), str(dest))

        # 如果是 zip 文件，解压
        if dest.suffix.lower() == ".zip":
            import zipfile
            with zipfile.ZipFile(dest, "r") as zf:
                zf.extractall(input_dir)

        now = utcnow_iso()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO jobs (id, status, created_at, updated_at, station, device, device_type, voltage_level, folder_path, external_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (job_id, "processing", now, now, station, device, device_type, voltage_level, str(input_dir), external_id or None),
            )

        asyncio.create_task(self._run_analysis(job_id, input_dir, device_type, voltage_level))

        return self.get_job(job_id)

    def get_job_by_external_id(self, external_id: str) -> dict | None:
        """通过外部系统 ID 查询任务。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE external_id = ?", (external_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def _resolve_skill_dir(self, skill_name: str) -> Path:
        """查找 skills 目录，兼容开发环境和 pip 安装部署。"""
        import os
        candidates = [
            # 环境变量显式指定
            Path(os.environ.get("NANOBOT_SKILLS_DIR", "")) / skill_name if os.environ.get("NANOBOT_SKILLS_DIR") else None,
            # 开发环境：相对于本文件向上 4 级到项目根
            Path(__file__).parent.parent.parent.parent / "skills" / skill_name,
            # 部署环境：nanobot workspace 下的 skills
            self.app_root.parent.parent / "skills" / skill_name,
            # 部署环境：项目根目录（pip install -e 或 git clone 场景）
            Path.cwd() / "skills" / skill_name,
        ]
        for d in candidates:
            if d and d.is_dir():
                return d
        raise FileNotFoundError(
            f"找不到 skills/{skill_name} 目录。"
            f"请设置环境变量 NANOBOT_SKILLS_DIR 指向 skills 目录的父目录，"
            f"或确认 skills/{skill_name} 已部署到以下位置之一: "
            + ", ".join(str(c) for c in candidates if c)
        )

    async def _run_analysis(self, job_id: str, input_dir: Path, device_type: str, voltage_level: str):
        """后台运行故障分析：9步流水线（对齐客户子Agent架构）"""
        import subprocess

        skill_dir = self._resolve_skill_dir("fault-analysis")
        scripts_dir = skill_dir / "scripts"
        refs_dir = skill_dir / "references"
        job_dir = input_dir.parent
        output_dir = job_dir / "output"
        output_dir.mkdir(exist_ok=True)
        para_dir = output_dir / "段落"
        para_dir.mkdir(exist_ok=True)

        def _run_script(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(skill_dir), encoding="utf-8")

        try:
            # ── Step 1: 解压压缩包（支持嵌套：zip→zwav→cfg/dat/hdr）──
            self._update_progress(job_id, 5, "正在解压录波文件...")
            self._extract_all_archives(input_dir, output_dir)

            # 故障录波 ZIP 可能在嵌套解压中未被处理，单独解压到所在目录
            import zipfile as _zipfile
            for _pass in range(3):
                remaining_zips = [zf for zf in output_dir.rglob("*.zip") if zf.is_file()]
                remaining_zips += [zf for zf in output_dir.rglob("*.ZIP") if zf.is_file()]
                if not remaining_zips:
                    break
                for zf in remaining_zips:
                    try:
                        with _zipfile.ZipFile(zf, 'r') as z:
                            names = z.namelist()
                        if not names:
                            continue
                        dest_dir = zf.parent
                        with _zipfile.ZipFile(zf, 'r') as z:
                            for name in z.namelist():
                                try:
                                    raw_bytes = name.encode('cp437')
                                    real_name = raw_bytes.decode('gbk')
                                except (UnicodeDecodeError, UnicodeEncodeError):
                                    real_name = name
                                dest_path = dest_dir / real_name
                                if name.endswith('/'):
                                    dest_path.mkdir(parents=True, exist_ok=True)
                                else:
                                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                                    with z.open(name) as s, open(dest_path, 'wb') as d:
                                        d.write(s.read())
                        print(f"  [解压-补充] {zf.name}")
                    except Exception as e:
                        print(f"  [解压-补充失败] {zf.name}: {e}")

            # ── Step 0: 解析文件夹名 → device_metadata.json ──
            self._update_progress(job_id, 8, "正在解析装置信息...")
            device_metadata = self._run_parse_folder_name(scripts_dir, output_dir, job_dir)

            # 从解析结果中回填 station/device/device_type/voltage_level
            self._fill_metadata_from_parsed(job_id, device_metadata, device_type, voltage_level)
            # 重新读取可能被更新的字段
            job = self.get_job(job_id)
            if job:
                device_type = job.get("device_type") or device_type
                voltage_level = job.get("voltage_level") or voltage_level

            # ── Step 2: 查找 CFG 文件（去重）──
            self._update_progress(job_id, 12, "正在查找录波配置文件...")
            cfg_files = list(output_dir.rglob("*.cfg")) + list(output_dir.rglob("*.CFG"))
            if not cfg_files:
                cfg_files = list(input_dir.rglob("*.cfg")) + list(input_dir.rglob("*.CFG"))
            # 去重：同一文件名只保留一个
            seen_stems: set[str] = set()
            unique_cfgs: list[Path] = []
            for cfg in cfg_files:
                if cfg.name not in seen_stems:
                    seen_stems.add(cfg.name)
                    unique_cfgs.append(cfg)
            cfg_files = unique_cfgs
            if not cfg_files:
                raise RuntimeError("未找到 .cfg 配置文件，请确认上传了 COMTRADE 格式的录波文件（.cfg + .dat + .hdr）")

            # ── Step 3: DAT → CSV ──
            self._update_progress(job_id, 18, f"正在解析 {len(cfg_files)} 个录波文件...")
            parse_script = scripts_dir / "parse_dat_to_csv.py"
            csv_dir = output_dir / "csv"
            csv_dir.mkdir(exist_ok=True)

            r = _run_script(["python", str(parse_script)] + [str(f) for f in cfg_files] + ["--output", str(csv_dir)])
            if r.returncode != 0:
                raise RuntimeError(f"DAT 解析失败: {r.stderr or r.stdout}")

            csv_files = list(csv_dir.rglob("*.csv"))
            if not csv_files:
                raise RuntimeError("DAT 解析后未生成 CSV 文件")

            # calculate_rms.py 期望 CFG 文件与 CSV 在同一目录
            # CSV 文件在子目录中（如 csv/安徽.屏显变_220kV母线第一套保护PCS915D/），
            # 需要将 CFG 复制到相同子目录，否则 calculate_rms.py 找不到 CFG
            for cfg in cfg_files:
                cfg_stem = cfg.stem.upper()
                matching_csv = None
                for csv_f in csv_files:
                    if csv_f.stem.upper() == cfg_stem:
                        matching_csv = csv_f
                        break
                if matching_csv:
                    dest = matching_csv.parent / cfg.name
                else:
                    dest = csv_dir / cfg.name
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(cfg, dest)

            # ── Step 4: 计算 RMS 统计 ──
            self._update_progress(job_id, 28, "正在计算 RMS 统计和事件...")
            rms_script = scripts_dir / "calculate_rms.py"
            rms_dir = output_dir / "rms"
            rms_dir.mkdir(exist_ok=True)

            r = _run_script(["python", str(rms_script)] + [str(f) for f in csv_files] + ["--output", str(rms_dir)])
            if r.returncode != 0:
                print(f"[fault-analysis] RMS 计算警告: {r.stderr}", flush=True)

            # ── Step 5: 故障发展分析 ──
            self._update_progress(job_id, 35, "正在分析故障发展过程...")
            self._run_fault_development(scripts_dir, csv_files, output_dir)

            # ── Step 6: 子Agent段落生成 ──
            self._update_progress(job_id, 40, "正在生成装置分析段落...")
            llm_client = self._get_llm_client()
            paragraphs = await self._generate_device_paragraphs(
                llm_client, cfg_files, output_dir, input_dir, para_dir,
                refs_dir, device_type, voltage_level, device_metadata, job_id,
            )

            # ── Step 6.5: 跨装置时序对齐 ──
            self._update_progress(job_id, 70, "正在对齐多装置时序...")
            self._run_cross_device_alignment(scripts_dir, output_dir, rms_dir)

            # ── Step 7: 管线校验 ──
            self._update_progress(job_id, 75, "正在校验分析完整性...")
            self._run_check_pipeline(scripts_dir, output_dir, para_dir)

            # ── Step 8: 主Agent组装最终报告 ──
            self._update_progress(job_id, 80, "正在调用 AI 组装最终报告...")
            report_md = await self._compose_final_report(
                llm_client, paragraphs, output_dir, refs_dir,
                device_type, voltage_level, device_metadata,
            )

            # 保存报告
            report_path = job_dir / "故障分析报告.md"
            report_path.write_text(report_md, encoding="utf-8")

            # 更新数据库
            file_size = report_path.stat().st_size
            mime_type = "text/markdown"
            download_token = generate_download_token()

            with self._conn() as conn:
                conn.execute(
                    """UPDATE jobs SET status = 'completed', updated_at = ?,
                       result_file_name = ?, result_relative_path = ?,
                       result_download_token = ?, result_mime_type = ?,
                       result_file_size = ?, progress = 100, progress_message = '分析完成'
                       WHERE id = ?""",
                    (utcnow_iso(), report_path.name, str(report_path),
                     download_token, mime_type, file_size, job_id),
                )

        except Exception as e:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE jobs SET status = 'failed', error_message = ?, updated_at = ? WHERE id = ?",
                    (str(e), utcnow_iso(), job_id),
                )

    # ──────────────────────────────────────────────────────────────
    # 流水线各步骤方法
    # ──────────────────────────────────────────────────────────────

    def _get_llm_client(self):
        """获取 LLM 客户端（优先 Claude settings → nanobot config）。"""
        import json as _json
        from webui.trip_briefing.llm.client import LLMClient

        provider = None
        claude_settings = Path.home() / ".claude" / "settings.json"
        if claude_settings.exists():
            try:
                settings = _json.loads(claude_settings.read_text(encoding="utf-8"))
                env = settings.get("env", {})
                base_url = env.get("ANTHROPIC_BASE_URL", "").replace("/anthropic", "/v1")
                api_key = env.get("ANTHROPIC_AUTH_TOKEN", "")
                model = env.get("ANTHROPIC_MODEL", "")
                if base_url and api_key and model:
                    provider = {"base_url": base_url, "api_key": api_key, "model": model}
            except Exception:
                pass

        if not provider:
            config_path = Path.home() / ".protection" / "config.json"
            if not config_path.exists():
                config_path = Path.home() / ".nanobot" / "config.json"
            if not config_path.exists():
                raise FileNotFoundError("缺少配置文件 config.json，无法调用 LLM")

            config_data = _json.loads(config_path.read_text(encoding="utf-8"))
            default_model = config_data.get("agents", {}).get("defaults", {}).get("model", "glm-4-flash")
            providers = config_data.get("providers", {})
            for name in ["zhipu", "dashscope", "deepseek", "openai", "openrouter"]:
                p = providers.get(name, {})
                if p.get("apiKey") or p.get("api_key"):
                    provider = {
                        "base_url": p.get("apiBase") or p.get("base_url", ""),
                        "api_key": p.get("apiKey") or p.get("api_key", ""),
                        "model": p.get("model", default_model),
                    }
                    break
            if not provider:
                for name, p in providers.items():
                    if p.get("apiKey") or p.get("api_key"):
                        provider = {
                            "base_url": p.get("apiBase") or p.get("base_url", ""),
                            "api_key": p.get("apiKey") or p.get("api_key", ""),
                            "model": p.get("model", default_model),
                        }
                        break

        if not provider or not provider.get("api_key"):
            raise ValueError("未找到有效的 LLM provider（已检查 ~/.claude/settings.json 和 ~/.nanobot/config.json）")

        return LLMClient(
            api_url=provider["base_url"],
            api_key=provider["api_key"],
            model=provider["model"],
            timeout=180,
            max_retries=3,
        )

    def _run_parse_folder_name(self, scripts_dir: Path, output_dir: Path, job_dir: Path) -> dict:
        """Step 0: 解析文件夹名 → device_metadata.json"""
        import subprocess
        import json as _json
        from loguru import logger

        script = scripts_dir / "parse_folder_name.py"
        if not script.exists():
            logger.warning("[fault-analysis] parse_folder_name.py 不存在: {}", script)
            return {}

        # 收集 output_dir 中所有录波文件路径作为输入（排除 csv 目录中的文件）
        input_paths = []
        for ext in ["*.cfg", "*.CFG", "*.hdr", "*.HDR"]:
            for f in output_dir.rglob(ext):
                # 跳过 csv 子目录中的文件（这些是后续步骤生成的）
                if f.parent.name == "csv":
                    continue
                input_paths.append(str(f))
        if not input_paths:
            logger.warning("[fault-analysis] output_dir 中未找到 cfg/hdr 文件: {}", output_dir)
            return {}

        logger.info("[fault-analysis] parse_folder_name 输入文件: {} 个", len(input_paths))
        try:
            r = subprocess.run(
                ["python", str(script)] + input_paths + ["--json"],
                capture_output=True, text=True, timeout=60, cwd=str(scripts_dir.parent), encoding="utf-8",
            )
            if r.returncode == 0 and r.stdout.strip():
                metadata = _json.loads(r.stdout.strip())
                # 保存到 job_dir
                meta_path = job_dir / "device_metadata.json"
                meta_path.write_text(_json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
                logger.info("[fault-analysis] parse_folder_name 成功，解析 {} 个设备", len(metadata) if isinstance(metadata, list) else 1)
                return metadata
            else:
                logger.error("[fault-analysis] parse_folder_name 失败: returncode={}, stderr={}", r.returncode, r.stderr[:500])
        except Exception as e:
            logger.error("[fault-analysis] parse_folder_name 异常: {}", e)
        return {}

    def _fill_metadata_from_parsed(self, job_id: str, metadata: dict, current_device_type: str, current_voltage_level: str):
        """从 parse_folder_name 的解析结果回填 job 的 station/device/device_type/voltage_level。"""
        from loguru import logger

        if not metadata:
            logger.warning("[fault-analysis] parse_folder_name 返回空结果，跳过元数据回填")
            return

        # metadata 可能是 list（多设备）或 dict（单设备）
        items = metadata if isinstance(metadata, list) else [metadata]
        if not items:
            return

        first = items[0]
        station = first.get("station") or ""
        device_name = first.get("device_name") or ""
        device_type_cn = first.get("device_type_cn") or ""
        voltage_kv = first.get("voltage_kv")

        logger.info("[fault-analysis] parse_folder_name 结果: station={}, device_name={}, device_type_cn={}, voltage_kv={}",
                     station, device_name, device_type_cn, voltage_kv)

        # 映射 device_type_cn 到后端使用的简短类型
        type_map = {
            "线路保护": "线路",
            "母差保护": "母差",
            "主变保护": "主变",
            "开关保护（断路器保护）": "开关保护",
            "配电设备": "配电设备",
        }
        parsed_device_type = type_map.get(device_type_cn, "")
        parsed_voltage = f"{voltage_kv}kV" if voltage_kv else ""

        # 只在用户未指定时才回填
        updates = {}
        if not current_device_type and parsed_device_type:
            updates["device_type"] = parsed_device_type
        if not current_voltage_level and parsed_voltage:
            updates["voltage_level"] = parsed_voltage

        # station 和 device_name 总是从解析结果回填（因为前端不再要求用户填写）
        if station:
            updates["station"] = station
        if device_name:
            updates["device"] = device_name

        if updates:
            with self._conn() as conn:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                values = list(updates.values()) + [utcnow_iso(), job_id]
                conn.execute(
                    f"UPDATE jobs SET {set_clause}, updated_at = ? WHERE id = ?",
                    values,
                )
            logger.info("[fault-analysis] 元数据已回填: {}", updates)
        else:
            logger.warning("[fault-analysis] 无可回填的元数据 (station={}, device_type={}, voltage={})",
                          station, parsed_device_type, parsed_voltage)

    def _run_fault_development(self, scripts_dir: Path, csv_files: list[Path], output_dir: Path):
        """Step 5: 故障发展分析（calculate_fault_development.py）"""
        import subprocess

        script = scripts_dir / "calculate_fault_development.py"
        if not script.exists():
            print("[fault-analysis] calculate_fault_development.py 不存在，跳过", flush=True)
            return

        for csv_file in csv_files:
            try:
                r = subprocess.run(
                    ["python", str(script), str(csv_file), "--output", str(output_dir)],
                    capture_output=True, text=True, timeout=120, cwd=str(scripts_dir.parent), encoding="utf-8",
                )
                if r.returncode != 0:
                    print(f"[fault-analysis] 故障发展分析警告 ({csv_file.name}): {r.stderr[:200]}", flush=True)
            except Exception as e:
                print(f"[fault-analysis] 故障发展分析异常 ({csv_file.name}): {e}", flush=True)

    def _collect_device_data_for_subagent(
        self, cfg_path: Path, output_dir: Path, input_dir: Path,
    ) -> str:
        """收集单个装置的所有数据，用于构造子Agent prompt。"""
        sections = []
        device_stem = cfg_path.stem

        # 0. 文件路径上下文（厂站名、套别通常在 .zwav 文件名中）
        # 向上查找包含中文的 .zwav 或文件夹名
        context_parts = []
        cur = cfg_path.parent
        for _ in range(5):
            if cur == output_dir or cur == cur.parent:
                break
            context_parts.append(cur.name)
            cur = cur.parent
        # 也查找同级 .zwav 文件
        zwav_files = list(cfg_path.parent.glob("*.zwav")) + list(cfg_path.parent.glob("*.ZWAV"))
        if context_parts or zwav_files:
            ctx = "### 文件路径上下文\n"
            if context_parts:
                ctx += f"- 所在目录链: {' / '.join(reversed(context_parts))}\n"
            if zwav_files:
                ctx += f"- 关联 .zwav 文件: {', '.join(f.name for f in zwav_files)}\n"
            ctx += f"- CFG 文件名: {cfg_path.name}\n"
            ctx += f"- 装置标识(stem): {device_stem}\n"
            sections.append(ctx)

        # 1. HDR 信息（GB18030 优先，因为 PCS-915D 等装置的 HDR 为 GB18030 编码）
        hdr_candidates = list(cfg_path.parent.glob("*.hdr")) + list(cfg_path.parent.glob("*.HDR"))
        if hdr_candidates:
            hdr_path = hdr_candidates[0]
            hdr_text = None
            for enc in ("gb18030", "utf-8"):
                try:
                    hdr_text = hdr_path.read_text(encoding=enc)
                    break
                except (UnicodeDecodeError, UnicodeError):
                    continue
            if hdr_text is None:
                hdr_text = hdr_path.read_text(encoding="utf-8", errors="replace")
            sections.append(f"### HDR 文件: {hdr_path.name}\n```xml\n{hdr_text[:150000]}\n```")

        # 2. Events CSV（calculate_rms.py 生成的文件名格式: {stem}.events.csv）
        events_csv = output_dir / "rms" / f"{device_stem}.events.csv"
        if not events_csv.exists():
            events_csv = output_dir / "rms" / f"{device_stem}_events.csv"
        if events_csv.exists():
            try:
                events_text = events_csv.read_text(encoding="utf-8", errors="replace")
                sections.append(f"### Events 文件: {events_csv.name}\n```csv\n{events_text[:20000]}\n```")
            except Exception:
                pass

        # 3. RMS CSV（calculate_rms.py 生成的文件名格式: {stem}.rms.csv）
        rms_csv = output_dir / "rms" / f"{device_stem}.rms.csv"
        if not rms_csv.exists():
            rms_csv = output_dir / "rms" / f"{device_stem}_rms.csv"
        if rms_csv.exists():
            try:
                rms_text = rms_csv.read_text(encoding="utf-8", errors="replace")
                sections.append(f"### RMS 文件: {rms_csv.name}\n```csv\n{rms_text[:20000]}\n```")
            except Exception:
                pass

        # 4. 故障发展数据 JSON
        dev_json = output_dir / f"{device_stem}.development.json"
        if dev_json.exists():
            try:
                dev_text = dev_json.read_text(encoding="utf-8")
                sections.append(f"### 故障发展过程数据: {dev_json.name}\n```json\n{dev_text}\n```")
            except Exception:
                pass

        return "\n\n".join(sections)

    def _detect_device_type_from_metadata(self, device_metadata: dict, cfg_path: Path) -> str:
        """从 device_metadata 或文件名推断设备类型。"""
        # 从 metadata 推断
        if isinstance(device_metadata, list):
            for item in device_metadata:
                if isinstance(item, dict):
                    dtype = item.get("device_type") or ""
                    if "母差" in dtype or "母线" in dtype or dtype == "busbar":
                        return "母差"
                    elif "主变" in dtype or "变压器" in dtype or dtype == "transformer":
                        return "主变"
                    elif "开关" in dtype or "断路器" in dtype or dtype == "breaker":
                        return "开关"
                    elif "电容" in dtype or "电抗" in dtype or dtype == "distribution":
                        return "配电"
                    elif dtype == "line":
                        return "线路"
        elif isinstance(device_metadata, dict):
            dtype = device_metadata.get("device_type") or ""
            if "母差" in dtype or "母线" in dtype:
                return "母差"
            elif "主变" in dtype or "变压器" in dtype:
                return "主变"

        # 从文件名推断
        name_lower = cfg_path.stem.lower()
        if "母差" in name_lower or "母线" in name_lower or "busbar" in name_lower:
            return "母差"
        elif "主变" in name_lower or "变压器" in name_lower:
            return "主变"
        elif "开关" in name_lower or "断路器" in name_lower:
            return "开关"
        elif "电容" in name_lower or "电抗" in name_lower:
            return "配电"
        return "线路"

    async def _generate_device_paragraphs(
        self,
        llm_client,
        cfg_files: list[Path],
        output_dir: Path,
        input_dir: Path,
        para_dir: Path,
        refs_dir: Path,
        device_type: str,
        voltage_level: str,
        device_metadata: dict,
        job_id: str = "",
    ) -> dict[str, str]:
        """Step 6: 对每个装置调用子Agent生成标准化段落。"""
        subagent_template_map = {
            "线路": "线路保护-prompt-template.md",
            "主变": "主变保护-prompt-template.md",
            "母差": "母差保护-prompt-template.md",
            "开关": "开关保护-prompt-template.md",
            "配电": "配电设备保护-prompt-template.md",
        }

        paragraphs: dict[str, str] = {}

        for i, cfg_path in enumerate(cfg_files):
            if job_id:
                self._update_progress(job_id, 40 + i * 15,
                                      f"正在分析装置 {i+1}/{len(cfg_files)}: {cfg_path.stem}...")
            # 推断设备类型（每个装置可能不同）
            dev_type = self._detect_device_type_from_metadata(device_metadata, cfg_path)
            template_file = refs_dir / "subagent" / subagent_template_map.get(dev_type, "线路保护-prompt-template.md")

            if not template_file.exists():
                print(f"[fault-analysis] 子Agent模板不存在: {template_file.name}，使用线路模板", flush=True)
                template_file = refs_dir / "subagent" / "线路保护-prompt-template.md"

            prompt_template = template_file.read_text(encoding="utf-8")

            # 收集该装置数据
            device_data = self._collect_device_data_for_subagent(cfg_path, output_dir, input_dir)

            # 构造 prompt
            prompt = f"""{prompt_template}

---

## 输入数据

以下是本套装置的录波分析数据，请严格按照上述模板格式提取信息并生成标准化段落。

{device_data}

**电压等级**: {voltage_level}
**设备类型**: {dev_type}
"""

            # 调用 LLM
            try:
                print(f"[fault-analysis] 子Agent LLM 调用开始: {cfg_path.stem}, prompt大小: {len(prompt)} chars", flush=True)
                response = await asyncio.to_thread(
                    llm_client.chat_completion,
                    messages=[{"role": "user", "content": prompt}],
                    model=llm_client.model,
                    max_tokens=8192,
                )
                if response.success:
                    paragraph = response.content
                    # 清理 code fence
                    if paragraph.startswith("```"):
                        lines = paragraph.split("\n")
                        if lines[0].startswith("```"):
                            lines = lines[1:]
                        if lines and lines[-1].strip() == "```":
                            lines = lines[:-1]
                        paragraph = "\n".join(lines)

                    # 保存段落文件
                    para_name = f"{cfg_path.stem}.md"
                    para_path = para_dir / para_name
                    para_path.write_text(paragraph, encoding="utf-8")
                    paragraphs[para_name] = paragraph
                    print(f"[fault-analysis] 子Agent段落已生成: {para_name}", flush=True)
                else:
                    print(f"[fault-analysis] 子Agent调用失败 ({cfg_path.name}): {response.error_message}", flush=True)
            except Exception as e:
                print(f"[fault-analysis] 子Agent异常 ({cfg_path.name}): {e}", flush=True)

        return paragraphs

    def _run_cross_device_alignment(self, scripts_dir: Path, output_dir: Path, rms_dir: Path):
        """Step 6.5: 跨装置时序对齐。"""
        import subprocess
        import json as _json

        # 收集所有 events.csv（calculate_rms.py 生成 *.events.csv，兼容 *_events.csv）
        events_csvs = list(rms_dir.glob("*.events.csv")) + list(rms_dir.glob("*_events.csv"))
        if len(events_csvs) < 2:
            print("[fault-analysis] 装置数 < 2，跳过跨装置对齐", flush=True)
            return

        # 生成 align_cross_device 所需的 JSON 输入
        events_by_device: dict[str, list] = {}
        for ecsv in events_csvs:
            device_name = ecsv.stem.replace("_events", "").replace("_Events", "")
            events = []
            try:
                lines = ecsv.read_text(encoding="utf-8-sig", errors="replace").splitlines()
                if len(lines) < 2:
                    continue
                for line in lines[1:]:
                    parts = line.split(",")
                    if len(parts) >= 3:
                        time_str = parts[0].strip()
                        channel = parts[1].strip()
                        content = parts[2].strip()
                        delta = 1 if "动作" in content else (-1 if "返回" in content else 0)
                        events.append({
                            "time": time_str,
                            "channel": channel,
                            "value": content,
                            "delta": delta,
                        })
            except Exception as e:
                print(f"[fault-analysis] 解析 events 失败 ({ecsv.name}): {e}", flush=True)
            if events:
                events_by_device[device_name] = events

        if len(events_by_device) < 2:
            return

        # 写入 JSON
        events_json_path = output_dir / "align_events_input.json"
        events_json_path.write_text(_json.dumps(events_by_device, ensure_ascii=False, indent=2), encoding="utf-8")

        # 执行 align_cross_device.py
        align_script = scripts_dir / "align_cross_device.py"
        if align_script.exists():
            try:
                r = subprocess.run(
                    ["python", str(align_script),
                     "--events-json", str(events_json_path),
                     "--ref-strategy", "earliest",
                     "--output", str(output_dir / "aligned.json")],
                    capture_output=True, text=True, timeout=60, cwd=str(scripts_dir.parent), encoding="utf-8",
                )
                if r.returncode != 0:
                    print(f"[fault-analysis] 跨装置对齐警告: {r.stderr[:200]}", flush=True)
            except Exception as e:
                print(f"[fault-analysis] 跨装置对齐异常: {e}", flush=True)

        # 执行 compare_devices.py
        compare_script = scripts_dir / "compare_devices.py"
        if compare_script.exists():
            try:
                r = subprocess.run(
                    ["python", str(compare_script)] + [str(f) for f in events_csvs] +
                    ["--output", str(output_dir / "多装置时序对比表.csv")],
                    capture_output=True, text=True, timeout=60, cwd=str(scripts_dir.parent), encoding="utf-8",
                )
                if r.returncode != 0:
                    print(f"[fault-analysis] 时序对比表警告: {r.stderr[:200]}", flush=True)
            except Exception as e:
                print(f"[fault-analysis] 时序对比表异常: {e}", flush=True)

    def _run_check_pipeline(self, scripts_dir: Path, output_dir: Path, para_dir: Path):
        """Step 7: 管线校验。"""
        import subprocess

        script = scripts_dir / "check_pipeline.py"
        if not script.exists():
            return

        # check_pipeline.py 检查 output_dir 下的 段落/ 目录
        try:
            r = subprocess.run(
                ["python", str(script), str(output_dir)],
                capture_output=True, text=True, timeout=30, cwd=str(scripts_dir.parent), encoding="utf-8",
            )
            if r.returncode != 0:
                print(f"[fault-analysis] 管线校验警告:\n{r.stdout[:500]}", flush=True)
            else:
                print(f"[fault-analysis] 管线校验通过", flush=True)
        except Exception as e:
            print(f"[fault-analysis] 管线校验异常: {e}", flush=True)

    async def _compose_final_report(
        self,
        llm_client,
        paragraphs: dict[str, str],
        output_dir: Path,
        refs_dir: Path,
        device_type: str,
        voltage_level: str,
        device_metadata: dict,
    ) -> str:
        """Step 8: 主Agent读取段落，按设备类型对应的模板组装最终报告。"""
        # 读取报告模板（完整，不截断）
        template_map = {
            "线路": "线路跳闸简报模板.md",
            "主变": "主变跳闸简报模板.md",
            "母差": "母差跳闸简报模板.md",
            "开关": "开关保护跳闸简报模板.md",
            "配电": "配电设备跳闸简报模板.md",
        }
        report_template_path = refs_dir / template_map.get(device_type, "线路跳闸简报模板.md")
        report_template = ""
        if report_template_path.exists():
            report_template = report_template_path.read_text(encoding="utf-8")

        # 读取电压等级开关速查表
        voltage_switch = ""
        vk_path = refs_dir / "电压等级保护配置知识.md"
        if vk_path.exists():
            try:
                full_vk = vk_path.read_text(encoding="utf-8")
                # 提取 §9 电压等级开关
                import re as _re
                m = _re.search(r"(## 9\. 电压等级开关.+?)(?=\n## \d+\.)", full_vk, _re.DOTALL)
                if m:
                    voltage_switch = m.group(1).strip()
            except Exception:
                pass

        # 读取跨装置对齐数据
        aligned_data = ""
        aligned_json = output_dir / "aligned.json"
        if aligned_json.exists():
            try:
                aligned_data = "### 跨装置时序对齐数据\n```json\n"
                aligned_data += aligned_json.read_text(encoding="utf-8")[:5000]
                aligned_data += "\n```\n"
            except Exception:
                pass

        compare_csv = output_dir / "多装置时序对比表.csv"
        if compare_csv.exists():
            try:
                aligned_data += "\n### 多装置时序对比表\n```csv\n"
                aligned_data += compare_csv.read_text(encoding="utf-8")[:5000]
                aligned_data += "\n```\n"
            except Exception:
                pass

        # 组装段落内容
        paragraphs_text = ""
        for name, content in paragraphs.items():
            paragraphs_text += f"\n\n---\n### 段落文件: {name}\n{content}"

        # 构造 prompt — 以报告模板为唯一章节依据
        prompt = f"""你是电网故障分析主Agent。你的任务是读取子Agent段落文件，**严格按照报告模板的章节结构**组装最终跳闸简报。

## 核心规则

1. **报告模板是唯一的章节依据**。必须严格按照下方「报告模板」中定义的章节顺序和内容输出，不要自行增删章节，不要套用其他设备类型的模板结构。

2. **数据来源**：只使用段落文件中提供的数据。段落中有的数据直接引用；段落中缺失的数据标注 `[无数据]` 或 `[待核实]`，**绝对不要编造数据**。

3. **电压等级开关**：根据下方「电压等级开关」规则，对当前设备类型和电压等级不适用的章节标注 N/A 并简要说明原因，不要强行输出无关内容。

4. **报告布局强制规则**：
   - 动作时序表按厂站分开，同厂站多套分列展示
   - 时序表仅列保护装置，故障录波器不入时序表
   - 保护装置与录波器分表展示
   - CT/PT 必须从段落中提取，不得留空
   - 所有保护装置必须 HDR + DAT 双源综合
   - 两套一致性分析按厂站分开（仅双重化配置）
   - 表格格式简洁优先

5. **标题格式**：报告标题包含厂站名称和设备名称，格式参照模板中的命名规则。

6. **段落数据完整性**：段落中包含 HDR信息、Events信息、RMS信息三个区块，主Agent从对应区块读取数据生成简报各章节。

## 电压等级开关

{voltage_switch if voltage_switch else "（未找到电压等级开关规则，请根据常识判断章节适用性）"}

## 报告模板（完整结构 — 必须严格遵循）

{report_template}

## 段落文件内容

{paragraphs_text}

## 跨装置对齐数据

{aligned_data}

## 设备信息

- **设备类型**: {device_type}
- **电压等级**: {voltage_level}

请严格按照报告模板的章节结构生成完整的跳闸简报。每个章节都不能省略，不适用的章节标注 N/A。
"""

        response = await asyncio.to_thread(
            llm_client.chat_completion,
            messages=[{"role": "user", "content": prompt}],
            model=llm_client.model,
            max_tokens=16384,
        )

        if not response.success:
            raise RuntimeError(f"主Agent LLM 调用失败: {response.error_message}")

        report = response.content
        # 清理 code fence
        if report.startswith("```"):
            lines = report.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            report = "\n".join(lines)

        return report

    def _update_progress(self, job_id: str, progress: int, message: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET progress = ?, progress_message = ?, updated_at = ? WHERE id = ?",
                (progress, message, utcnow_iso(), job_id),
            )

    def _extract_all_archives(self, input_dir: Path, output_dir: Path):
        """递归解压所有压缩包（支持 zip/zwav/rar/7z），处理嵌套结构。"""
        import zipfile

        archive_exts = {'.zip', '.zwav', '.rar', '.7z', '.tar', '.gz', '.tgz'}
        processed: set[Path] = set()

        def _extract_zip(src: Path, dest: Path):
            """解压 ZIP/ZWAV 文件，自动处理 GBK 编码文件名。"""
            with zipfile.ZipFile(src, 'r') as zf:
                for name in zf.namelist():
                    try:
                        raw_bytes = name.encode('cp437')
                        real_name = raw_bytes.decode('gbk')
                    except (UnicodeDecodeError, UnicodeEncodeError):
                        real_name = name
                    dest_path = dest / real_name
                    if name.endswith('/'):
                        dest_path.mkdir(parents=True, exist_ok=True)
                    else:
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(name) as s, open(dest_path, 'wb') as d:
                            d.write(s.read())

        def _extract_once():
            """扫描 output_dir 中未处理的压缩包并解压，返回是否有新解压。"""
            found_new = False
            for arc in list(output_dir.rglob("*")):
                if not arc.is_file() or arc.suffix.lower() not in archive_exts:
                    continue
                if arc in processed:
                    continue
                processed.add(arc)
                suffix = arc.suffix.lower()
                try:
                    if suffix == '.zwav':
                        # .zwav 解压到父目录（与上传压缩包解压逻辑一致）
                        # 文件夹名已由 downloader 用 stName_equipmentName 命名，
                        # parse_folder_name.py 依赖该文件夹名提取元数据
                        _extract_zip(arc, arc.parent)
                    elif suffix == '.zip':
                        _extract_zip(arc, output_dir)
                    elif suffix == '.rar':
                        import subprocess
                        try:
                            subprocess.run(['unrar', 'x', '-o+', str(arc), str(output_dir)],
                                           check=True, capture_output=True)
                        except (subprocess.CalledProcessError, FileNotFoundError):
                            try:
                                subprocess.run(['rar', 'x', '-o+', str(arc), str(output_dir)],
                                               check=True, capture_output=True)
                            except (subprocess.CalledProcessError, FileNotFoundError):
                                pass
                    elif suffix == '.7z':
                        import subprocess
                        try:
                            subprocess.run(['7z', 'x', f'-o{output_dir}', '-y', str(arc)],
                                           check=True, capture_output=True)
                        except (subprocess.CalledProcessError, FileNotFoundError):
                            pass
                    print(f"  [解压] {arc.name}")
                    found_new = True
                except Exception as e:
                    print(f"  [解压失败] {arc.name}: {e}")
            return found_new

        # 复制 input_dir 中的压缩包到 output_dir（保留相对路径，维持目录结构）
        import shutil as _shutil
        for f in input_dir.rglob("*"):
            if f.is_file() and f.suffix.lower() in archive_exts:
                rel = f.relative_to(input_dir)
                dest = output_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                _shutil.copy2(f, dest)

        # 循环解压直到没有新的压缩包（处理嵌套：zip→zwav→cfg/dat/hdr）
        for _ in range(10):  # 最多 10 层，防止意外
            if not _extract_once():
                break

        # 如果 input_dir 中直接有 cfg/dat/hdr（非压缩包上传），复制到 output_dir（保留相对路径）
        for ext in ['*.cfg', '*.CFG', '*.dat', '*.DAT', '*.hdr', '*.HDR']:
            for f in input_dir.rglob(ext):
                rel = f.relative_to(input_dir)
                dest = output_dir / rel
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    _shutil.copy2(f, dest)

    def update_evaluation(self, job_id: str, evaluation: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET evaluation = ?, updated_at = ? WHERE id = ?",
                (evaluation, utcnow_iso(), job_id),
            )

    def delete_job(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if not job:
            return False

        # 删除文件
        job_dir = self.jobs_dir / job_id
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)

        # 删除数据库记录
        with self._conn() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

        return True

    def get_report_content(self, job_id: str) -> str | None:
        job = self.get_job(job_id)
        if not job or not job.get("result_relative_path"):
            return None

        report_path = Path(job["result_relative_path"])
        if not report_path.exists():
            return None

        return report_path.read_text(encoding="utf-8")

    def get_report_path(self, job_id: str) -> Path | None:
        job = self.get_job(job_id)
        if not job or not job.get("result_relative_path"):
            return None

        report_path = Path(job["result_relative_path"])
        return report_path if report_path.exists() else None

    def export_jobs(self, job_ids: list[str]) -> io.BytesIO | None:
        zip_buffer = io.BytesIO()
        has_files = False

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for job_id in job_ids:
                job = self.get_job(job_id)
                if not job or not job.get("result_relative_path"):
                    continue

                report_path = Path(job["result_relative_path"])
                if report_path.exists():
                    arcname = f"{job.get('station', 'unknown')}_{job.get('device', '')}_{job_id}.md"
                    zf.write(report_path, arcname)
                    has_files = True

        if not has_files:
            return None

        zip_buffer.seek(0)
        return zip_buffer

    def _row_to_dict(self, row) -> dict:
        if row is None:
            return {}

        _str_fields = [
            "station", "device", "device_type", "voltage_level", "folder_path", "external_id",
        ]

        if hasattr(row, "keys"):
            d = dict(row)
        else:
            d = {
                "id": row[0], "status": row[1], "created_at": row[2],
                "updated_at": row[3], "created_by": row[4], "error_message": row[5],
                "station": row[6], "device": row[7], "device_type": row[8],
                "voltage_level": row[9], "folder_path": row[10],
                "result_file_name": row[11], "result_relative_path": row[12],
                "result_download_token": row[13], "result_mime_type": row[14],
                "result_file_size": row[15], "progress": row[16],
                "progress_message": row[17], "evaluation": row[18],
                "external_id": row[19] if len(row) > 19 else "",
            }

        for k in _str_fields:
            if d.get(k) is None:
                d[k] = ""

        # 添加下载和预览 URL
        if d.get("result_download_token"):
            d["download_url"] = f"/api/fault-analysis/jobs/{d['id']}/download"
            d["preview_url"] = f"/api/fault-analysis/jobs/{d['id']}/preview"

        return d
