// md2pdf print step: HTML file -> PDF with a real footer page number.
// We use Puppeteer's page.pdf({footerTemplate}) because Chromium's CLI
// --print-to-pdf cannot render footers, and Chromium ignores CSS @page margin
// boxes (counter(page)). Puppeteer fills .pageNumber / .totalPages for us.
//
// Usage: node print.js <htmlPath> <outPath>
const puppeteer = require("puppeteer");

(async () => {
  const [htmlPath, outPath] = process.argv.slice(2);
  if (!htmlPath || !outPath) {
    console.error("usage: node print.js <htmlPath> <outPath>");
    process.exit(2);
  }

  const browser = await puppeteer.launch({
    // Nix-provided, supply-chain-clean Chromium (same one mermaid-cli uses).
    executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });
  try {
    const page = await browser.newPage();
    // Content is fully static (mermaid is pre-rendered to inline SVG, fonts fall
    // back to local Noto when offline), so 'load' is enough — don't wait on network.
    await page.goto("file://" + htmlPath, { waitUntil: "load", timeout: 30000 });

    await page.pdf({
      path: outPath,
      format: "A4",
      printBackground: true,
      displayHeaderFooter: true,
      headerTemplate: "<div></div>",
      footerTemplate:
        '<div style="font-size:9px;color:#94A3B8;width:100%;text-align:center;' +
        'font-family:Inter,\'Noto Sans SC\',sans-serif;">' +
        '<span class="pageNumber"></span> / <span class="totalPages"></span>' +
        "</div>",
      margin: { top: "12mm", bottom: "16mm", left: "12mm", right: "12mm" },
    });
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
