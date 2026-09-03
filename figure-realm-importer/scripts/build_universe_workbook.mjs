import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";


const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) {
  throw new Error("usage: build_universe_workbook.mjs INPUT.json OUTPUT.xlsx");
}

const payload = JSON.parse(await fs.readFile(inputPath, "utf8"));
if (!Array.isArray(payload.universes) || payload.universes.length === 0) {
  throw new Error("workbook payload contains no universes");
}

const workbook = Workbook.create();
for (const [index, universe] of payload.universes.entries()) {
  const sheet = workbook.worksheets.add(universe.sheetName);
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);

  const matrix = [payload.columns, ...universe.rows];
  const lastRow = matrix.length;
  const usedRange = sheet.getRange(`A1:F${lastRow}`);
  usedRange.values = matrix;

  const header = sheet.getRange("A1:F1");
  header.format = {
    fill: "#17365D",
    font: { bold: true, color: "#FFFFFF" },
    rowHeight: 26,
    verticalAlignment: "center",
  };

  if (lastRow > 1) {
    sheet.getRange(`A2:F${lastRow}`).format = {
      verticalAlignment: "top",
      rowHeight: 20,
    };
    sheet.getRange(`B2:B${lastRow}`).format.numberFormat = "@";
    sheet.getRange(`E2:E${lastRow}`).format.numberFormat = "0";
  }

  sheet.getRange(`A1:A${lastRow}`).format.columnWidth = 34;
  sheet.getRange(`B1:B${lastRow}`).format.columnWidth = 15;
  sheet.getRange(`C1:C${lastRow}`).format.columnWidth = 18;
  sheet.getRange(`D1:D${lastRow}`).format.columnWidth = 56;
  sheet.getRange(`E1:E${lastRow}`).format.columnWidth = 14;
  sheet.getRange(`F1:F${lastRow}`).format.columnWidth = 72;

  const table = sheet.tables.add(`A1:F${lastRow}`, true, `UniverseProducts${index + 1}`);
  table.showFilterButton = true;
  table.showBandedRows = true;
}

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
