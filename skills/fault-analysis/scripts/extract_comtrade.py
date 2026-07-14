# -*- coding: utf-8 -*-
"""
解压COMTRADE录波文件压缩包

支持格式：.zip, .rar, .7z, .tar.gz, .tgz, .ZWAV

用法：
    # 解压到指定目录（自动跳过已存在的文件）
    python <skill>/scripts/extract_comtrade.py 录波文件.zip --output D:/data/事故文件夹

    # 批量解压
    python <skill>/scripts/extract_comtrade.py D:/data/压缩包/*.zip --output D:/data/事故文件夹

    # <skill> 为本技能根目录（如 ~/.workbuddy/skills/comtrade-parser）

注意：
    - 默认跳过已存在cfg/dat/hdr文件的压缩包，避免重复解压
    - 如果需要强制解压，请先删除已存在的文件
"""
import argparse
import os
import shutil
import subprocess
from pathlib import Path


def extract_zip(zip_path, output_dir):
    """解压ZIP文件，自动处理GBK编码文件名
    
    zip 规范默认以 cp437(IBM437) 编码文件名，中文 Windows 归档 zip 常以 GBK 写入。
    Python zipfile 的 namelist() 按 cp437 解码为 Unicode 字符串，对中文显示为乱码。
    本函数以 cp437→GBK 回路还原真实中文名后解压，避免乱码目录/文件名。
    
    用法示例：
        >>> extract_zip("2026-06-18屏显变母线故障.zip", Path("output/"))
        [GBK解码] 安徽.屏显变_220kV母线第一套保护PCS915D_...zwav
        [GBK解码] 安徽.屏显变_220kV母线第二套保护SGB750D_...zwav
    """
    import zipfile
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for name in zf.namelist():
                # 还原原始字节（cp437→GBK 回路）
                try:
                    raw_bytes = name.encode('cp437')
                    real_name = raw_bytes.decode('gbk')
                except (UnicodeDecodeError, UnicodeEncodeError):
                    real_name = name  # 不是 GBK，保持原样
                
                dest = Path(output_dir) / real_name
                
                if name.endswith('/'):
                    # 目录条目
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(name) as src:
                        with open(dest, 'wb') as dst:
                            dst.write(src.read())
                    
                    if real_name != name:
                        # 印出解码结果（截断长名）
                        short_src = name[:60] + '...' if len(name) > 60 else name
                        short_dst = real_name[:100] + '...' if len(real_name) > 100 else real_name
                        print(f"  [GBK解码] {short_src} → {short_dst}")
            return True
    except Exception as e:
        print(f"  解压错误: {e}")
        return False


def extract_rar(rar_path, output_dir):
    """解压RAR文件"""
    # 尝试使用unrar命令
    try:
        subprocess.run(['unrar', 'x', rar_path, output_dir], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    # 尝试使用rar命令
    try:
        subprocess.run(['rar', 'x', rar_path, output_dir, '-y'], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    # 尝试使用rarfile（Python库）
    try:
        import rarfile
        with rarfile.RarFile(rar_path) as rf:
            rf.extractall(path=output_dir)
        return True
    except ImportError:
        return False


def extract_7z(archive_path, output_dir):
    """解压7Z文件"""
    try:
        subprocess.run(['7z', 'x', archive_path, f'-o{output_dir}', '-y'], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    try:
        import py7zr
        with py7zr.SevenZipFile(archive_path, mode='r') as zf:
            zf.extractall(path=output_dir)
        return True
    except ImportError:
        return False


def extract_tar(tar_path, output_dir):
    """解压TAR文件（包括.tar.gz, .tgz）"""
    import tarfile
    with tarfile.open(tar_path, 'r:*') as tf:
        tf.extractall(output_dir)
    return True


def extract_archive(archive_path, output_dir, skip_existing=True):
    """自动识别并解压压缩包

    Args:
        archive_path: 压缩包路径
        output_dir: 输出目录（基础目录，如 output/）
        skip_existing: 是否跳过已存在的文件（默认True）
    """
    archive_path = Path(archive_path)

    if not archive_path.exists():
        print(f"  文件不存在: {archive_path}")
        return False, None

    # 计算相对路径，保持原路径结构
    # 找到保护录波或故障录波所在的层级
    rel_parts = None
    archive_parts = archive_path.parts
    for i, part in enumerate(archive_parts):
        if '保护录波' in part or '故障录波' in part:
            rel_parts = archive_parts[i:]
            break

    # 确定目标目录：如果有相对路径，保持子目录结构
    if rel_parts and len(rel_parts) > 1:
        # rel_parts 包含 保护录波/厂站/套别/文件名.zip
        # 输出到 output_dir/保护录波/厂站/套别/
        target_dir = output_dir / Path(*rel_parts[:-1])  # 去掉文件名，保留目录结构
    else:
        # 没有保护录波/故障录波层级，直接用 output_dir
        target_dir = output_dir

    target_dir.mkdir(parents=True, exist_ok=True)

    # 检查目标目录中是否已存在解压后的文件
    if skip_existing:
        existing_files = set()
        for ext in ['.cfg', '.dat', '.hdr', '.inf', '.cff']:
            existing_files.update(target_dir.glob(f'*{ext}'))

        if existing_files:
            print(f"  跳过解压：已存在 {len(existing_files)} 个文件")
            return True, list(existing_files)

    suffix = archive_path.suffix.lower()
    suffixes = [archive_path.stem.split('.')[-1].lower()] if '.' in archive_path.stem else []

    success = False
    extracted_files = []

    # ZIP (包括 .ZWAV)
    if suffix in ['.zip', '.zwav', '.ZWAV'] or 'zip' in suffixes:
        success = extract_zip(archive_path, target_dir)

    # RAR
    elif suffix == '.rar' or 'rar' in suffixes:
        success = extract_rar(archive_path, target_dir)

    # 7Z
    elif suffix in ['.7z', '.001']:
        success = extract_7z(archive_path, target_dir)

    # TAR/GZ
    elif suffix in ['.tar', '.gz', '.tgz'] or 'tar' in suffixes:
        success = extract_tar(archive_path, target_dir)

    if success:
        # 查找解压后的文件
        for root, dirs, files in os.walk(target_dir):
            for file in files:
                file_path = Path(root) / file
                if file_path.suffix.lower() in ['.cfg', '.dat', '.hdr', '.inf', '.cff']:
                    extracted_files.append(file_path)

        return True, extracted_files

    return False, []


def batch_extract(archive_paths, output_dir, skip_existing=True):
    """批量解压多个压缩包到同一目录

    Args:
        archive_paths: 压缩包路径列表
        output_dir: 输出目录
        skip_existing: 是否跳过已存在文件的压缩包（默认True）
    """
    results = []

    for archive_path in archive_paths:
        archive_path = Path(archive_path)

        print(f"\n处理: {archive_path.name}")
        print("-" * 60)

        success, extracted_files = extract_archive(archive_path, output_dir, skip_existing)

        result = {
            'archive': str(archive_path),
            'success': success,
            'files': extracted_files
        }
        results.append(result)

        if success:
            if extracted_files:
                # 检查是否跳过了已存在的文件
                if skip_existing and len(extracted_files) > 0:
                    existing_in_dir = set()
                    for ext in ['.cfg', '.dat', '.hdr']:
                        existing_in_dir.update(output_dir.glob(f'*{ext}'))
                    if existing_in_dir:
                        print(f"  ✓ 已存在文件，跳过解压")
                else:
                    print(f"  ✓ 解压成功")
                    file_types = {}
                    for f in extracted_files:
                        ext = f.suffix.lower()
                        file_types[ext] = file_types.get(ext, 0) + 1
                    print(f"  发现文件: {dict(file_types)}")
        else:
            print(f"  ✗ 解压失败（不支持的格式或缺少工具）")

    return results


def main():
    parser = argparse.ArgumentParser(description='解压COMTRADE录波文件压缩包')
    parser.add_argument('archives', nargs='+', help='压缩包路径（支持*.zip, *.rar, *.7z, *.tar.gz等）')
    parser.add_argument('--output', '-o', type=str, default=None,
                        help='输出目录（默认：项目目录/output，保持原路径结构）')

    args = parser.parse_args()

    # 默认输出到当前工作目录下的 output 目录
    if args.output:
        output_dir = Path(args.output)
    else:
        # 旧实现用 script_dir.parent.parent.parent 推断项目根，
        # 在技能安装目录下会错误地指向 .workbuddy/output；改为 cwd/output
        output_dir = Path.cwd() / 'output'

    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("COMTRADE录波文件解压工具")
    print("=" * 60)
    print(f"输出目录: {output_dir.absolute()}")
    print()

    # 检查解压工具
    tools_available = []
    if shutil.which('unrar') or shutil.which('rar'):
        tools_available.append('RAR')
    if shutil.which('7z'):
        tools_available.append('7Z')

    if tools_available:
        print(f"检测到工具: {', '.join(tools_available)}")
    print()

    # 处理文件
    archive_paths = [Path(p) for p in args.archives]

    # 如果是通配符，展开
    if len(archive_paths) == 1:
        p = archive_paths[0]
        if '*' in str(p) or '?' in str(p):
            parent = p.parent if p.parent != Path('.') else Path('.')
            archive_paths = list(parent.glob(p.name))
            if not archive_paths:
                print(f"错误: 未找到匹配的文件: {p}")
                return

    results = batch_extract(archive_paths, output_dir)

    # 总结
    print("\n" + "=" * 60)
    print("解压总结")
    print("=" * 60)

    success_count = sum(1 for r in results if r['success'])
    total_count = len(results)

    print(f"总计: {success_count}/{total_count} 个文件解压成功")

    if success_count > 0:
        # 统计所有解压出的文件
        all_files = []
        for r in results:
            if r['files']:
                all_files.extend(r['files'])

        if all_files:
            file_types = {}
            for f in all_files:
                ext = f.suffix.lower()
                file_types[ext] = file_types.get(ext, 0) + 1

            print("\n发现的文件类型:")
            for ext, count in sorted(file_types.items()):
                print(f"  {ext}: {count} 个")


if __name__ == '__main__':
    main()
