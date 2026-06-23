# -*- coding: utf-8 -*-
"""Pipeline 流程编排"""
import logging
import re
import shutil
import zipfile
from pathlib import Path
from typing import List, Optional, Callable

from webui.trip_briefing.models import DeviceFiles, PipelineConfig
from webui.trip_briefing.llm.client import LLMClient, LLMResponse

logger = logging.getLogger(__name__)


def strip_code_fences(text: str) -> str:
    """
    清理 LLM 输出中的 markdown code fence 包裹。
    移除开头的 ```markdown 和结尾的 ``` 标记。
    """
    text = text.strip()
    # 移除开头的 ```markdown 或 ```lang
    text = re.sub(r'^```\w*\n?', '', text)
    # 移除结尾的 ```
    text = re.sub(r'\n?```$', '', text)
    return text.strip()


# 匹配 {xxx} 占位符，但排除正常的 Markdown 格式（如 **{text}**）和代码块中的内容
_PLACEHOLDER_RE = re.compile(r'\{[^{}]{1,20}\}')


def strip_placeholders(text: str) -> str:
    """
    清理 LLM 输出中未替换的模板占位符（如 {值}、{程序版本}）。
    表格行中的占位符替换为 `-`，非表格行替换为 "未获取到数据"。
    """
    lines = text.split('\n')
    result = []
    for line in lines:
        if _PLACEHOLDER_RE.search(line):
            is_table_row = '|' in line and line.strip().startswith('|')
            if is_table_row:
                line = _PLACEHOLDER_RE.sub('-', line)
            else:
                line = _PLACEHOLDER_RE.sub('未获取到数据', line)
        result.append(line)
    return '\n'.join(result)


def read_file_auto_encode(file_path: str) -> Optional[str]:
    """
    自动检测编码读取文件。UTF-8 优先，失败尝试 GB18030。

    Args:
        file_path: 文件路径

    Returns:
        文件内容字符串，失败返回 None
    """
    path = Path(file_path)
    if not path.exists():
        return None

    for encoding in ("utf-8", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue

    logger.warning(f"无法解码文件: {file_path}")
    return None


def _find_zip_files(directory: Path) -> List[Path]:
    """
    查找目录中所有 zip 格式文件（包括 .zip 和 .ZWAV 等非标准扩展名）。
    """
    zip_files = []
    for f in directory.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix.lower() == ".zip":
            zip_files.append(f)
        else:
            try:
                with zipfile.ZipFile(f, 'r'):
                    zip_files.append(f)
            except (zipfile.BadZipFile, IOError):
                pass
    return sorted(zip_files)


def _fix_zip_encoding(target: Path, zf: zipfile.ZipFile) -> None:
    """修复 zip 解压后的中文文件名乱码（Windows GBK -> UTF-8）。"""
    renames = []
    for info in zf.infolist():
        try:
            raw = info.filename.encode('cp437')
            try:
                decoded = raw.decode('utf-8')
            except UnicodeDecodeError:
                decoded = raw.decode('gbk')
        except (UnicodeDecodeError, UnicodeEncodeError):
            continue
        if decoded != info.filename:
            renames.append((info.filename, decoded))
    # 从深到浅排序，避免重命名父目录后子路径失效
    renames.sort(key=lambda x: x[0].count('/'), reverse=True)
    for orig, decoded in renames:
        src = target / orig
        dst = target / decoded
        if not src.exists() or src == dst:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            # 目录可能包含未被重命名的子项（如纯 ASCII 文件名），需要逐个移动
            dst.mkdir(exist_ok=True)
            for child in src.iterdir():
                child.rename(dst / child.name)
            try:
                src.rmdir()
            except OSError:
                pass
        else:
            src.rename(dst)


def _unwrap_single_child_dirs(target: Path, max_depth: int = 3) -> None:
    """如果解压后只有一层子目录，自动将其内容上移（最多 max_depth 层）。"""
    for _ in range(max_depth):
        sub_dirs = [p for p in target.iterdir() if p.is_dir()]
        files = [p for p in target.iterdir() if p.is_file()]
        if len(sub_dirs) != 1 or files:
            break  # 不止一个子目录或有同级文件，不展开
        wrapper = sub_dirs[0]
        print(f"  [解压] 展开包裹目录: {wrapper.name}/", flush=True)
        for item in list(wrapper.iterdir()):
            dest = target / item.name
            if dest.exists():
                continue
            shutil.move(str(item), str(dest))
        try:
            wrapper.rmdir()
        except OSError:
            break


def unzip_archives(input_dir: Path, work_dir: Path) -> int:
    """
    扫描 input_dir 中的压缩包并解压到 work_dir，保留目录结构。
    解压后删除 work_dir 中对应的压缩包。

    Args:
        input_dir: 输入目录（包含压缩包）
        work_dir: 工作目录（解压目标）

    Returns:
        解压的文件数
    """
    zip_files = _find_zip_files(input_dir)
    count = 0
    for zip_path in zip_files:
        rel = zip_path.relative_to(input_dir)
        target = work_dir / rel.parent
        target.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(target)
                _fix_zip_encoding(target, zf)
            # 自动展开解压后多余的包裹目录
            _unwrap_single_child_dirs(target)
            count += 1
            print(f"  解压: {zip_path.name} -> {target}", flush=True)
            # 删除 work_dir 中的压缩包副本
            work_copy = work_dir / rel
            if work_copy.exists():
                work_copy.unlink()
        except Exception as e:
            logger.error(f"解压失败 {zip_path}: {e}")

    return count


def prepare_work_dir(input_dir: Path, work_dir: Path) -> Path:
    """
    准备工作目录。

    复制输入目录到 work_dir，解压所有压缩包（.zip/.ZWAV 等），删除压缩包副本。

    Args:
        input_dir: 输入目录
        work_dir: 工作目录（解压目标）

    Returns:
        实际的工作目录路径
    """
    zip_files = _find_zip_files(input_dir)

    if zip_files:
        print(f"[解压] 发现 {len(zip_files)} 个压缩包", flush=True)
        work_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(input_dir, work_dir, dirs_exist_ok=True)
        unzip_archives(input_dir, work_dir)
        return work_dir
    else:
        return input_dir


def collect_device_files(
    device_dir: Path,
    station: str,
    set_number: str,
) -> DeviceFiles:
    """
    从一个装置目录中收集文件路径。

    Args:
        device_dir: 装置目录路径
        station: 厂站名
        set_number: 套别

    Returns:
        DeviceFiles 实例
    """
    hdr_files = [f for f in device_dir.iterdir() if f.suffix.lower() == ".hdr"]
    rms_files = [f for f in device_dir.iterdir() if f.name.lower().endswith(".rms.csv")]
    events_files = [f for f in device_dir.iterdir() if f.name.lower().endswith(".events.csv")]

    return DeviceFiles(
        station=station,
        set_number=set_number,
        hdr_path=str(hdr_files[0]) if hdr_files else None,
        rms_csv_path=str(rms_files[0]) if rms_files else None,
        events_csv_path=str(events_files[0]) if events_files else None,
    )


def _has_device_files(d: Path) -> bool:
    """判断目录中是否包含装置文件（.hdr / .rms.csv / .events.csv / .cfg）"""
    _exts = {".hdr", ".cfg"}
    _name_ends = (".rms.csv", ".events.csv")
    for f in d.iterdir():
        low = f.name.lower()
        if f.suffix.lower() in _exts or any(low.endswith(e) for e in _name_ends):
            return True
    return False


def scan_devices(
    input_dir: Path,
    sub_dir: str = "保护录波",
) -> List[DeviceFiles]:
    """
    扫描事故文件夹，收集所有保护装置的文件路径。

    目录结构：
    保护录波/厂站/套别/*.cfg,*.dat,*.hdr,*.csv
    故障录波/厂站/*.cfg,*.dat,*.hdr,*.csv

    支持内层 zip 解压后多一层包裹目录的情况（自动向下搜索直到找到装置文件）。

    Args:
        input_dir: 事故文件夹根路径
        sub_dir: 子目录名（"保护录波" 或 "故障录波"）

    Returns:
        DeviceFiles 列表
    """
    base = input_dir / sub_dir
    if not base.exists():
        # 打印工作目录结构帮助调试
        print(f"  [scan] 目录不存在: {base}", flush=True)
        if input_dir.exists():
            print(f"  [scan] 工作目录内容: {[p.name for p in input_dir.iterdir()]}", flush=True)
        return []

    devices = []

    if sub_dir == "保护录波":
        # 保护录波/厂站/套别/  (也可能多一层包裹目录)
        for station_dir in sorted(base.iterdir()):
            if not station_dir.is_dir():
                continue
            station_name = station_dir.name
            set_dirs = [d for d in sorted(station_dir.iterdir()) if d.is_dir()]
            # 检查是否直接包含装置文件（扁平结构）
            if _has_device_files(station_dir) and not set_dirs:
                devices.append(collect_device_files(
                    station_dir, station=station_name, set_number="",
                ))
                continue
            for set_dir in set_dirs:
                set_name = set_dir.name
                sub_dirs = [d for d in sorted(set_dir.iterdir()) if d.is_dir()]
                # 如果 set_dir 直接包含装置文件
                if _has_device_files(set_dir):
                    devices.append(collect_device_files(
                        set_dir, station=station_name, set_number=set_name,
                    ))
                elif sub_dirs:
                    # 多一层包裹：把下级目录当作套别
                    for sub in sub_dirs:
                        if _has_device_files(sub):
                            devices.append(collect_device_files(
                                sub, station=station_name, set_number=sub.name,
                            ))
                        else:
                            # 再向下一级
                            for sub2 in sorted(sub.iterdir()):
                                if sub2.is_dir() and _has_device_files(sub2):
                                    devices.append(collect_device_files(
                                        sub2, station=station_name, set_number=sub2.name,
                                    ))
    else:
        # 故障录波/厂站/（无套别层，也可能多一层包裹目录）
        for station_dir in sorted(base.iterdir()):
            if not station_dir.is_dir():
                continue
            station_name = station_dir.name
            sub_dirs = [d for d in sorted(station_dir.iterdir()) if d.is_dir()]
            if _has_device_files(station_dir) and not sub_dirs:
                # 厂站目录直接包含文件
                devices.append(collect_device_files(
                    station_dir, station=station_name, set_number="",
                ))
            elif sub_dirs:
                for sub in sub_dirs:
                    if _has_device_files(sub):
                        devices.append(collect_device_files(
                            sub, station=station_name, set_number=sub.name,
                        ))
                    else:
                        # 可能多一层包裹
                        for sub2 in sorted(sub.iterdir()):
                            if sub2.is_dir() and _has_device_files(sub2):
                                devices.append(collect_device_files(
                                    sub2, station=station_name, set_number=sub2.name,
                                ))

    return devices


def run_process_scripts(
    work_dir: Path,
) -> bool:
    """
    直接调用解析函数处理工作目录中的 COMTRADE 文件。
    不使用 subprocess，避免 uv run 启动开销。

    Args:
        work_dir: 工作目录（包含 .cfg 文件）

    Returns:
        全部成功返回 True，任一失败返回 False
    """
    from webui.trip_briefing.parser import process_all_comtrade

    success, failed = process_all_comtrade(work_dir)
    return failed == 0 and success > 0


def get_prompt_builder(device_type: str, role: str) -> Callable:
    """
    根据 device_type 和 role 获取对应的 prompt 构建函数。

    Args:
        device_type: "line" | "transformer" | "bus" | "fault_recorder"
        role: "subagent" | "main_agent"

    Returns:
        prompt 构建函数
    """
    # device_type -> (subagent_module, main_agent_module)
    module_map = {
        "line": "webui.trip_briefing.llm.prompts.line.subagent",
        "transformer": "webui.trip_briefing.llm.prompts.transformer.subagent",
        "bus": "webui.trip_briefing.llm.prompts.bus.subagent",
        "fault_recorder": "webui.trip_briefing.llm.prompts.fault_recorder.subagent",
    }

    if device_type not in module_map:
        raise ValueError(f"未知的设备类型: {device_type}")

    # fault_recorder 只有 subagent
    if device_type == "fault_recorder" and role == "main_agent":
        raise ValueError("fault_recorder 不支持 main_agent role")

    # subagent 在子模块，main_agent 在子模块
    if role == "main_agent":
        module_path = module_map[device_type].replace(".subagent", ".main_agent")
    else:
        module_path = module_map[device_type]

    import importlib
    module = importlib.import_module(module_path)
    func_name = f"build_{role}_prompt"

    return getattr(module, func_name)


def generate_paragraph(
    device: DeviceFiles,
    llm_client,
    device_type: str,
    output_dir: Path,
    monitor: "Monitor",
    config: "PipelineConfig" = None,
) -> LLMResponse:
    """
    Step 7: 为单套装置生成段落。

    读取 HDR/RMS/Events 文件，构造 subagent prompt，调用 LLM，保存段落 .md。

    Args:
        device: 装置文件信息
        llm_client: LLM 客户端
        device_type: 设备类型
        output_dir: 输出目录
        monitor: 监控器

    Returns:
        LLMResponse
    """
    # 读取文件内容
    hdr_content = read_file_auto_encode(device.hdr_path) if device.hdr_path else ""
    rms_content = read_file_auto_encode(device.rms_csv_path) if device.rms_csv_path else ""
    events_content = read_file_auto_encode(device.events_csv_path) if device.events_csv_path else ""

    # 构造 prompt
    prompt_type = device_type if device_type != "fault_recorder" else "fault_recorder"
    build_prompt = get_prompt_builder(prompt_type, "subagent")
    prompt_text = build_prompt(
        hdr_content=hdr_content or "",
        rms_content=rms_content or "",
        events_content=events_content or "",
        station=device.station,
        set_number=device.set_number,
    )

    # 调用 LLM（带硬超时）
    subagent_timeout_s = config.subagent_timeout if config else 120

    with monitor.track("subagent", device=device.label) as tracker:
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

        def _call_llm():
            return llm_client.chat_completion(
                messages=[{"role": "user", "content": prompt_text}],
                model=llm_client.model,
                max_tokens=config.subagent_max_tokens if config else 4096,
            )

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_call_llm)
            try:
                response = future.result(timeout=subagent_timeout_s)
            except FutureTimeoutError:
                logger.error(f"子 Agent LLM 调用超时 ({subagent_timeout_s}s): {device.label}")
                return LLMResponse(
                    success=False,
                    error_message=f"子 Agent LLM 调用超时（{subagent_timeout_s}秒）: {device.label}",
                )

        tracker.input_tokens = response.prompt_tokens
        tracker.output_tokens = response.completion_tokens
        tracker.total_tokens = response.total_tokens

    if response.success:
        # 保存段落（清理 code fence）
        content = strip_placeholders(strip_code_fences(response.content))
        para_dir = output_dir / "段落"
        para_dir.mkdir(parents=True, exist_ok=True)
        para_path = para_dir / f"{device.label}.md"
        para_path.write_text(content, encoding="utf-8")

    return response


def generate_briefing(
    paragraphs_dir: Path,
    llm_client,
    device_type: str,
    output_dir: Path,
    monitor: "Monitor",
    config: "PipelineConfig" = None,
) -> LLMResponse:
    """
    Step 8: 读取所有段落，生成完整简报。
    当输出被截断时自动续写，最多 3 轮。

    Args:
        paragraphs_dir: 段落目录
        llm_client: LLM 客户端
        device_type: 设备类型
        output_dir: 输出目录
        monitor: 监控器

    Returns:
        LLMResponse
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

    # 读取所有段落
    paragraphs = []
    for para_file in sorted(paragraphs_dir.glob("*.md")):
        content = para_file.read_text(encoding="utf-8")
        paragraphs.append(f"### 段落: {para_file.stem}\n{content}")

    if not paragraphs:
        logger.error("没有可用的段落文件")
        return LLMResponse(success=False, error_message="没有可用的段落文件")

    all_paragraphs = "\n\n---\n\n".join(paragraphs)

    # 构造 prompt
    build_prompt = get_prompt_builder(device_type, "main_agent")
    prompt_text = build_prompt(paragraphs_content=all_paragraphs)

    timeout_s = config.main_agent_timeout if config else 300
    max_tokens = config.main_agent_max_tokens if config else 16384
    TRUNCATION_THRESHOLD = max_tokens - 100  # 接近上限视为截断
    MAX_CONTINUATIONS = 3

    all_content_parts: list[str] = []
    total_input_tokens = 0
    total_output_tokens = 0

    current_messages = [{"role": "user", "content": prompt_text}]

    for round_idx in range(1 + MAX_CONTINUATIONS):
        with monitor.track("main_agent" if round_idx == 0 else "main_agent_cont") as tracker:
            def _call_llm(msgs=current_messages):
                return llm_client.chat_completion(
                    messages=msgs,
                    model=llm_client.model,
                    max_tokens=max_tokens,
                )

            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_call_llm)
                try:
                    response = future.result(timeout=timeout_s)
                except FutureTimeoutError:
                    logger.error(f"主 Agent LLM 调用超时 ({timeout_s}s)")
                    return LLMResponse(
                        success=False,
                        error_message=f"主 Agent LLM 调用超时（{timeout_s}秒），请稍后重试",
                    )

            tracker.input_tokens = response.prompt_tokens
            tracker.output_tokens = response.completion_tokens
            tracker.total_tokens = response.total_tokens
            total_input_tokens += response.prompt_tokens
            total_output_tokens += response.completion_tokens

        if not response.success:
            # 前几轮失败但已有内容，继续保存
            break

        all_content_parts.append(response.content)

        # 检查是否被截断
        is_truncated = response.completion_tokens >= TRUNCATION_THRESHOLD
        if not is_truncated or round_idx >= MAX_CONTINUATIONS:
            break

        # 被截断，发起续写
        logger.warning(f"主 Agent 输出被截断 ({response.completion_tokens} tokens)，发起续写 (第 {round_idx + 1} 次)")
        current_messages = [
            {"role": "user", "content": prompt_text},
            {"role": "assistant", "content": response.content},
            {"role": "user", "content": "请继续输出上文未完成的内容，从断点处接着写，不要重复已有内容。"},
        ]

    # 合并所有内容
    full_content = strip_placeholders(strip_code_fences("\n".join(all_content_parts)))
    briefing_path = output_dir / "跳闸简报.md"
    briefing_path.write_text(full_content, encoding="utf-8")

    return LLMResponse(
        success=True,
        content=full_content,
        prompt_tokens=total_input_tokens,
        completion_tokens=total_output_tokens,
        total_tokens=total_input_tokens + total_output_tokens,
    )


def run_pipeline(
    input_dir: Path,
    output_dir: Path,
    device_type: str,
    config: PipelineConfig,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> int:
    """
    完整 Pipeline 执行入口。

    Args:
        input_dir: 事故文件夹路径
        output_dir: 输出目录
        device_type: 设备类型
        config: Pipeline 配置
        progress_callback: 进度回调函数 (progress: int, message: str)

    Returns:
        退出码 (0=成功, 2=部分失败)
    """
    from webui.trip_briefing.llm.client import LLMClient
    from webui.trip_briefing.monitor import Monitor

    def report_progress(progress: int, message: str) -> None:
        if progress_callback:
            try:
                progress_callback(progress, message)
            except Exception:
                pass

    output_dir.mkdir(parents=True, exist_ok=True)
    monitor = Monitor(output_dir=output_dir)

    # Step 0: 准备工作目录（解压 zip 或直接使用 input_dir）
    report_progress(30, "正在准备工作目录...")
    work_dir = prepare_work_dir(input_dir, output_dir / "work")

    # Step 1-3: 运行解析脚本
    report_progress(35, "正在运行解析脚本...")
    print("[Step 1-3] 运行解析脚本...", flush=True)
    with monitor.track("scripts"):
        scripts_ok = run_process_scripts(
            work_dir=work_dir,
        )

    # 扫描装置（从工作目录）
    report_progress(40, "正在扫描装置...")
    devices = scan_devices(work_dir, sub_dir="保护录波")
    fault_recorders = scan_devices(work_dir, sub_dir="故障录波")

    # Step 4: 多装置时序对比（可选，不影响主流程）
    if scripts_ok and len(devices) > 1:
        try:
            from webui.trip_briefing.scripts.compare_devices import compare_devices as _compare_devices
            events_files = [Path(d.events_csv_path) for d in devices if d.events_csv_path]
            if events_files:
                compare_output = work_dir / "多装置时序对比表.csv"
                _compare_devices(events_files, compare_output)
                print(f"[Step 4] 多装置时序对比表已生成: {compare_output}", flush=True)
        except Exception as e:
            logger.warning(f"多装置时序对比失败（不影响主流程）: {e}")

    # Step 5: 合并电流突变信息（可选）
    if scripts_ok and len(devices) > 1:
        try:
            from webui.trip_briefing.scripts.calculate_rms import merge_current_mutation_files
            rms_csv_files = [d.rms_csv_path for d in devices if d.rms_csv_path]
            if rms_csv_files:
                merge_current_mutation_files(rms_csv_files, output_dir=str(work_dir))
                print(f"[Step 5] 电流突变信息汇总已生成", flush=True)
        except Exception as e:
            logger.warning(f"电流突变信息合并失败（不影响主流程）: {e}")

    print(f"[扫描] 发现 {len(devices)} 套保护装置, {len(fault_recorders)} 个故障录波器", flush=True)

    if not devices and not fault_recorders:
        # 打印目录结构帮助调试
        print(f"[ERROR] 未找到任何保护装置文件，工作目录: {work_dir}", flush=True)
        actual_dirs = []
        for p in sorted(work_dir.iterdir()):
            if p.is_dir():
                actual_dirs.append(p.name)
                print(f"  [dir] {p.name}/", flush=True)
        # 构造具体错误信息
        if not actual_dirs:
            error_detail = "ZIP 解压后为空，请检查压缩包内容"
        elif "保护录波" not in actual_dirs and "故障录波" not in actual_dirs:
            error_detail = (
                f"未找到「保护录波」或「故障录波」目录，"
                f"实际目录为：{', '.join(actual_dirs)}。"
                f"请参照录波文件上传手册整理目录结构"
            )
        else:
            error_detail = "目录下未找到 .cfg/.dat/.hdr 等装置文件"
        logger.error(f"未找到任何保护装置文件: {error_detail}")
        raise FileNotFoundError(error_detail)

    # 创建 LLM 客户端
    report_progress(45, "正在创建 LLM 客户端...")
    llm_client = LLMClient(
        api_url=config.api_url,
        api_key=config.api_key,
        model=config.model,
        timeout=config.timeout,
        max_retries=config.max_retries,
        enable_thinking=config.enable_thinking,
    )

    # Step 7: 生成段落
    failed_count = 0
    all_devices = list(devices) + list(fault_recorders)
    total_devices = len(all_devices)

    for idx, device in enumerate(all_devices):
        dtype = device_type
        # 故障录波目录下的装置使用 fault_recorder prompt
        if device in fault_recorders:
            dtype = "fault_recorder"

        # 计算进度: 45% - 85% 用于生成段落
        progress = 45 + int((idx / total_devices) * 40)
        report_progress(progress, f"正在生成段落: {device.label} ({idx + 1}/{total_devices})")

        print(f"[Step 7] 生成段落: {device.label} ...", flush=True)
        result = generate_paragraph(
            device=device,
            llm_client=llm_client,
            device_type=dtype,
            output_dir=output_dir,
            monitor=monitor,
            config=config,
        )
        if not result.success:
            failed_count += 1
            # 创建失败标记段落
            para_dir = output_dir / "段落"
            para_dir.mkdir(parents=True, exist_ok=True)
            (para_dir / f"{device.label}.md").write_text(
                f"## {device.label}\n\n[段落生成失败: {result.error_message}]",
                encoding="utf-8",
            )

    # Step 8: 合成简报
    report_progress(90, "正在合成跳闸简报...")
    print("[Step 8] 生成跳闸简报 ...", flush=True)
    paragraphs_dir = output_dir / "段落"
    briefing_result = generate_briefing(
        paragraphs_dir=paragraphs_dir,
        llm_client=llm_client,
        device_type=device_type,
        output_dir=output_dir,
        monitor=monitor,
        config=config,
    )

    # 保存监控日志
    report_progress(93, "正在保存监控日志...")
    monitor.save_log()
    print(f"[完成] 监控日志已保存", flush=True)

    if not briefing_result.success:
        return 2

    report_progress(95, "解析完成")
    return 0 if failed_count == 0 else 2
