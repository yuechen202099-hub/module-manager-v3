import type { MaterialGroup, ProjectSummary } from '@/api/types'

export type BarcodeVerificationPresentation = {
  status: NonNullable<MaterialGroup['barcodeVerification']>['status']
  label: string
  type: 'success' | 'warning' | 'info' | 'primary' | 'danger'
  passedCount: number
  totalCount: number
  progressLabel: string
  source: { key: 'machine' | 'manual' | 'none'; label: string }
  eligible: boolean
  reason: string
}

export type PhotoCategoryPresentation = {
  status: 'complete' | 'duplicate' | 'missing' | 'invalid_count'
  label: string
  type: 'success' | 'warning' | 'danger'
  classifiedCount: number
  totalCount: number
}

export type BarcodeDashboardPresentation = {
  checked: number
  passed: number
  failed: number
  unreadable: number
  notEligible: number
  rate: number
  rateLabel: string
}

export function mapBarcodeVerificationState(input?: Partial<MaterialGroup>): BarcodeVerificationPresentation
export function mapPhotoCategoryState(input?: Partial<MaterialGroup>): PhotoCategoryPresentation
export function mapBarcodeDashboardState(input?: Partial<ProjectSummary>): BarcodeDashboardPresentation
