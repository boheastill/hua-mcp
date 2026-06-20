// md2pdf print step: HTML file -> PDF with a real footer page number, plus a bounded
// two-way auto-fit that tidies a sparse trailing page.
//
// Why footer via Puppeteer: Chromium's CLI --print-to-pdf can't render footers and
// ignores CSS @page margin boxes, so page numbers need page.pdf({footerTemplate}).
//
// Auto-fit (only when last page is < HALF full):
//   1) try SHRINK to one fewer page (best: fewer pages). Accept iff shrink >= MIN_SCALE
//      AND a re-render actually drops a page.
//   2) else ENLARGE a little so the last page looks fuller, WITHOUT adding a page.
//      Accept iff scale <= MAX_SCALE AND a re-render keeps the same page count.
// Every change is verified by re-counting pages, so we never make it worse. Uniform
// scaling => the reader just sees slightly larger/smaller type, not a layout glitch.
//
// Usage: node print.js <htmlPath> <outPath>
const fs = require("fs");
const puppeteer = require("puppeteer");

const MM = 96 / 25.4; // CSS px per mm at 96dpi
const PRINTABLE_H = (297 - 12 - 16) * MM; // A4 height minus top/bottom margins
const PRINTABLE_W = (210 - 12 - 12) * MM; // A4 width minus left/right margins
const MIN_SCALE = 0.92; // don't shrink past this just to save a page
const MAX_SCALE = 1.12; // don't enlarge past this just to fill a page
const FULL_ENOUGH = 0.5; // last page >= 50% full => leave it alone

const FOOTER =
  '<div style="font-size:9px;color:#94A3B8;width:100%;text-align:center;' +
  "font-family:Inter,'Noto Sans SC',sans-serif;\">" +
  '<span class="pageNumber"></span> / <span class="totalPages"></span></div>';

const pdfOpts = (scale) => ({
  format: "A4",
  printBackground: true,
  displayHeaderFooter: true,
  headerTemplate: "<div></div>",
  footerTemplate: FOOTER,
  margin: { top: "12mm", bottom: "16mm", left: "12mm", right: "12mm" },
  scale,
});

function countPages(buf) {
  // page.pdf() returns a Uint8Array in Puppeteer v24; wrap so .toString decodes bytes.
  const m = Buffer.from(buf).toString("latin1").match(/\/Type\s*\/Page(?![s])/g);
  return m ? m.length : 1;
}

(async () => {
  const [htmlPath, outPath] = process.argv.slice(2);
  if (!htmlPath || !outPath) {
    console.error("usage: node print.js <htmlPath> <outPath>");
    process.exit(2);
  }

  const browser = await puppeteer.launch({
    executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });
  try {
    const page = await browser.newPage();
    // Measure at the print width so wrapping (and thus height) matches the PDF.
    // Keep viewport height small: scrollHeight is never less than the viewport, which
    // would over-report height for content shorter than the viewport (hiding shrink cases).
    await page.setViewport({ width: Math.round(PRINTABLE_W), height: 100 });
    await page.goto("file://" + htmlPath, { waitUntil: "load", timeout: 30000 });

    let buf = await page.pdf(pdfOpts(1));
    const pages = countPages(buf);
    let action = "keep", applied = 1;

    if (pages >= 2) {
      const contentH = await page.evaluate(() => document.documentElement.scrollHeight);
      const fill = contentH / PRINTABLE_H - (pages - 1); // how full the last page is (approx)

      if (fill > 0 && fill < FULL_ENOUGH) {
        // 1) Prefer shrinking the whole doc into one fewer page.
        const sDown = ((pages - 1) * PRINTABLE_H) / contentH * 0.99;
        if (sDown >= MIN_SCALE && sDown < 1) {
          const b = await page.pdf(pdfOpts(sDown));
          if (countPages(b) < pages) { buf = b; action = "shrink"; applied = sDown; }
        }
        // 2) Otherwise enlarge a little to fill the last page (stay at `pages`).
        if (action === "keep") {
          const sUp = Math.min(MAX_SCALE, ((pages - 0.1) * PRINTABLE_H) / contentH);
          if (sUp > 1.01) {
            const b = await page.pdf(pdfOpts(sUp));
            if (countPages(b) === pages) { buf = b; action = "enlarge"; applied = sUp; }
          }
        }
      }
      console.error(`[md2pdf print] pages=${pages} lastFill=${fill.toFixed(2)} -> ${action} scale=${applied.toFixed(3)}`);
    }

    fs.writeFileSync(outPath, buf);
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
