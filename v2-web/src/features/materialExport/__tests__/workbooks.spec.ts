import { describe, expect, it } from 'vitest'
import { Workbook } from 'exceljs'
import { buildSupplementWorkbook, buildTerminalWorkbook } from '../workbooks'

describe('material export workbooks', () => {
  it('builds the exact terminal workbook columns', async () => {
    const bytes = await buildTerminalWorkbook([{ meterNo: 'M-1', address: '总清单地址', moduleNo: 'MOD-1', finalCollectorNo: 'C-1' }])
    const workbook = new Workbook()
    await workbook.xlsx.load(bytes.buffer as ArrayBuffer)
    const worksheet = workbook.getWorksheet('终端资料')!
    expect(worksheet.getSheetValues().slice(1).map((row: any) => row.slice(1))).toEqual([
      ['表号', '地址', '模块号', '采集器号'],
      ['M-1', '总清单地址', 'MOD-1', 'C-1'],
    ])
  })

  it('omits an empty supplement workbook', async () => {
    expect(await buildSupplementWorkbook([])).toBeNull()
  })
})
