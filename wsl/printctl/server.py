"""printctl MCP — 纯 Go 免驱打印与扫描引擎。

提供四个核心物理工具:
1. print_file: 打印图片或 PDF 文档 (自动白底拍平、防切边排版)
2. scan_document: 物理光学扫描纸张 (75~600 DPI, 支持 JPG/PDF)
3. printer_status: 查询打印机在线状态与就绪遥测
4. discover_printers: 局域网毫秒级扫描可用网络打印机
"""
import pathlib
import subprocess
import sys

for _p in pathlib.Path(__file__).resolve().parents:
    if (_p / "huamcp.py").exists():
        sys.path.insert(0, str(_p))
        break
import huamcp  # noqa: E402

BIN_PATH = "/home/bohea/print/printctl/bin/printctl"

mcp = huamcp.server(__file__)


def _to_wsl_path(path_str: str) -> pathlib.Path:
    p_str = path_str.strip().strip('"').strip("'")
    # Windows drive path conversion e.g. C:\Users\... or E:\...
    if len(p_str) >= 2 and p_str[1] == ":" and p_str[0].isalpha():
        drive = p_str[0].lower()
        rest = p_str[2:].replace("\\", "/").lstrip("/")
        return pathlib.Path(f"/mnt/{drive}/{rest}")
    return pathlib.Path(p_str).expanduser()


@mcp.tool()
def print_file(file_path: str, printer_ip: str = "") -> str:
    """物理打印一张图片 (PNG, JPG, WebP) 或 PDF 文件。

    【参数】
    file_path: 要打印的图片或 PDF 文件绝对路径 (支持 Windows 路径如 E:\... 或 WSL 路径)。
    printer_ip: 可选，打印机 IP 地址（省略时自动在局域网自发现）。

    【功能】
    自动进行 Alpha 拍平（杜绝透明 PNG 打印成大黑底）、自动计算 A4 比例等比缩放、
    强制预留 5mm 硬件物理安全边距防裁切。若输入为 PDF，自动光栅化为 300 DPI 高清流发送至硬件。
    """
    p = _to_wsl_path(file_path)
    if not p.is_file():
        return f"错误: 待打印文件不存在: {file_path} (WSL 解析路径: {p})"

    # If input is a PDF, rasterize pages to 300 DPI high-quality JPEGs to prevent G3030 hardware rejection
    files_to_print = [str(p)]
    if p.suffix.lower() == ".pdf":
        try:
            import pymupdf
            doc = pymupdf.open(str(p))
            tmp_images = []
            tmp_dir = pathlib.Path("/tmp/printctl_pdf_pages")
            tmp_dir.mkdir(parents=True, exist_ok=True)
            for page_idx in range(len(doc)):
                page = doc[page_idx]
                pix = page.get_pixmap(dpi=300)
                page_out = tmp_dir / f"page_{page_idx+1}.jpg"
                pix.save(str(page_out))
                tmp_images.append(str(page_out))
            doc.close()
            if tmp_images:
                files_to_print = tmp_images
        except Exception as e:
            pass

    cmd = [BIN_PATH, "print"] + files_to_print + ["--json"]
    if printer_ip.strip():
        cmd.extend(["--ip", printer_ip.strip()])

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if res.returncode == 0:
            return f"✅ 打印任务已成功发送至打印机！文件: {file_path}\n{res.stdout}"
        return f"❌ 打印失败: {res.stderr or res.stdout}"
    except Exception as e:
        return f"❌ 执行异常: {e}"


@mcp.tool()
def scan_document(output_path: str = "/tmp/scanned.jpg", dpi: int = 300, printer_ip: str = "") -> str:
    """触发物理扫描仪，将扫描台上的纸张扫描保存为 JPG 图片或 PDF 文档。

    【参数】
    output_path: 扫描后保存的文件绝对路径 (支持 Windows 路径如 D:\... 或 WSL 路径)。
    dpi: 扫描分辨率，支持 75, 150, 300 (默认), 600 (超高清照片级)。
    printer_ip: 可选，打印机 IP 地址（省略时自动在局域网自发现）。

    【功能】
    通过 eSCL REST 协议驱动机身光学扫描头移动，将真实世界的纸张/手写笔记转化为数字位图流并保存。
    """
    p = _to_wsl_path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    cmd = [BIN_PATH, "scan", str(p), "--dpi", str(dpi), "--json"]
    if printer_ip.strip():
        cmd.extend(["--ip", printer_ip.strip()])

    try:
        # 600 DPI needs more time
        timeout = 90 if dpi >= 600 else 45
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if res.returncode == 0 and p.is_file():
            return f"✅ 物理扫描成功！文件已保存至: {output_path} (大小: {p.stat().st_size} 字节, 分辨率: {dpi} DPI)"
        return f"❌ 扫描失败: {res.stderr or res.stdout}"
    except Exception as e:
        return f"❌ 扫描执行异常: {e}"


@mcp.tool()
def printer_status(printer_ip: str = "") -> str:
    """查询局域网打印机的实时在线状态与扫描仪就绪情况。

    【参数】
    printer_ip: 可选，打印机 IP（省略时自动在局域网自发现）。
    """
    cmd = [BIN_PATH, "status", "--json"]
    if printer_ip.strip():
        cmd.extend(["--ip", printer_ip.strip()])

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return res.stdout or res.stderr
    except Exception as e:
        return f"❌ 查询异常: {e}"


@mcp.tool()
def discover_printers() -> str:
    """在局域网内进行并发探测，自动寻找所有支持 IPP Everywhere 与 eSCL 的网络打印机。"""
    cmd = [BIN_PATH, "discover", "--json"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return res.stdout or res.stderr
    except Exception as e:
        return f"❌ 探测异常: {e}"


if __name__ == "__main__":
    huamcp.run(mcp)
