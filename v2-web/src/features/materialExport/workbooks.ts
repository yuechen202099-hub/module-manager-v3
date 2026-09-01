import type { MaterialExportMeterRow, MaterialExportSupplementRow } from '../../api/types'

async function workbookBytes(sheetName: string, headers: string[], rows: string[][]): Promise<Uint8Array> {
  const { Workbook } = await import('exceljs')
  const workbook = new Workbook()
  const worksheet = workbook.addWorksheet(sheetName)
  worksheet.addRow(headers)
  for (const row of rows) worksheet.addRow(row)
  worksheet.getRow(1).font = { bold: true }
  worksheet.columns.forEach((column) => { column.width = 24 })
  const buffer = await workbook.xlsx.writeBuffer()
  return new Uint8Array(buffer)
}

export async function buildTerminalWorkbook(rows: MaterialExportMeterRow[]): Promise<Uint8Array> {
  return workbookBytes('终端资料', ['表号', '地址', '模块号', '采集器号'], rows.map((row) => [
    row.meterNo,
    row.address,
    row.moduleNo,
    row.finalCollectorNo,
  ]))
}

export async function buildSupplementWorkbook(rows: MaterialExportSupplementRow[]): Promise<Uint8Array | null> {
  if (!rows.length) return null
  return workbookBytes('补充采集器', ['采集器号', '照片文件名'], rows.map((row) => [row.collectorNo, row.photoFilename]))
}
