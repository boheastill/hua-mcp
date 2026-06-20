"""md2pdf renderer — markdown → premium PDF, fully offline.

Pipeline (vendored & de-branded from tech-grinder/proposal_renderer):
  1. Pre-render every ```mermaid``` block to an inline base64 SVG via local mmdc
     (no network; degrades back to a code block on failure).
  2. markdown2 → HTML body.
  3. Inject into a Jinja2 template + CSS theme.
  4. Headless Chromium --print-to-pdf for high-fidelity layout (CJK-safe).

Chromium and the CJK fonts are expected from the Nix flake in this directory
(PUPPETEER_EXECUTABLE_PATH / FONTCONFIG_FILE), so the server stays self-contained.
"""

import os
import re
import json
import base64
import subprocess
import tempfile
from datetime import datetime

from jinja2 import Environment, FileSystemLoader
import markdown2

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Md2Pdf:
    def __init__(self):
        self.base_dir = BASE_DIR
        self.templates_dir = os.path.join(self.base_dir, "templates")
        # Local npm-installed mmdc — kills the npx cold-start / network jitter.
        self.mmdc_path = os.path.join(self.base_dir, "node_modules", ".bin", "mmdc")
        self.env = Environment(loader=FileSystemLoader(self.templates_dir))
        self.template = self.env.get_template("document.html")

    # --- mermaid: offline vector render --------------------------------------
    def _render_mermaid_to_base64_svg(self, code: str) -> str:
        """Pure offline SVG generator: mermaid source -> embeddable data URI."""
        pup_cfg = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8")
        # --no-sandbox is required inside WSL/Nix headless containers.
        pup_cfg.write(json.dumps({"args": ["--no-sandbox", "--disable-setuid-sandbox"]}))
        pup_cfg.close()

        temp_in = tempfile.NamedTemporaryFile(suffix=".mmd", delete=False, mode="w", encoding="utf-8")
        temp_in.write(code)
        temp_in.close()
        temp_out = temp_in.name + ".svg"

        try:
            cmd = [self.mmdc_path, "-i", temp_in.name, "-o", temp_out, "-p", pup_cfg.name]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if result.returncode != 0:
                raise RuntimeError(f"mmdc exited {result.returncode}: {result.stderr[-300:]}")
            with open(temp_out, "r", encoding="utf-8") as f:
                svg_content = f.read()
            svg_b64 = base64.b64encode(svg_content.encode("utf-8")).decode("utf-8")
            return f"data:image/svg+xml;base64,{svg_b64}"
        finally:
            for p in (pup_cfg.name, temp_in.name, temp_out):
                if os.path.exists(p):
                    os.remove(p)

    def _replace_mermaid_with_images(self, markdown_content: str) -> str:
        def replacer(match):
            code = match.group(1).strip()
            try:
                data_uri = self._render_mermaid_to_base64_svg(code)
                return f"![diagram]({data_uri})"
            except Exception:
                # Degrade: keep the source as a fenced block so the body still prints.
                return "```mermaid\n" + code + "\n```"

        pattern = r"```mermaid\n(.*?)\n```"
        return re.sub(pattern, replacer, markdown_content, flags=re.DOTALL)

    # --- main entry ----------------------------------------------------------
    def render_to_pdf(
        self,
        markdown_content: str,
        output_path: str,
        *,
        title: str | None = None,
        subtitle: str | None = None,
        author: str | None = None,
        lang: str = "en",
        job_id: str = "doc",
    ) -> str:
        """Render a markdown string to a PDF file at ``output_path``. Returns the path."""
        md_with_images = self._replace_mermaid_with_images(markdown_content)
        html_body = markdown2.markdown(
            md_with_images,
            extras=["tables", "fenced-code-blocks", "cuddled-lists", "task_list", "strike"],
        )
        final_html = self.template.render(
            content=html_body,
            title=title,
            subtitle=subtitle,
            author=author,
            lang=lang,
            date=datetime.now().strftime("%Y-%m-%d"),
        )

        temp_html_path = os.path.join(tempfile.gettempdir(), f"md2pdf_{job_id}_{os.getpid()}.html")
        with open(temp_html_path, "w", encoding="utf-8") as f:
            f.write(final_html)

        # Render via Puppeteer (print.js): Chromium's CLI --print-to-pdf can't draw a
        # footer, and Chromium ignores CSS @page margin boxes, so page numbers need
        # page.pdf({footerTemplate}). node + puppeteer come from the Nix env.
        print_js = os.path.join(self.base_dir, "print.js")
        cmd = ["node", print_js, temp_html_path, output_path]
        try:
            # Timeout guard so a wedged headless browser can't hang the daemon.
            result = subprocess.run(cmd, cwd=self.base_dir, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                raise RuntimeError(f"puppeteer print failed: {result.stderr[-400:]}")
            if not os.path.exists(output_path):
                raise RuntimeError("puppeteer produced no output file")
            return output_path
        finally:
            if os.path.exists(temp_html_path):
                os.remove(temp_html_path)


if __name__ == "__main__":
    # Tiny smoke CLI:  python renderer.py in.md out.pdf
    import sys

    src = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else "# Hello\n\nmd2pdf works."
    out = sys.argv[2] if len(sys.argv) > 2 else "out.pdf"
    print(Md2Pdf().render_to_pdf(src, out, title="md2pdf"))
