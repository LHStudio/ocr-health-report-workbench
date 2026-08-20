export const defaultOcrApiUrl = String(import.meta.env.VITE_OCR_API_URL || '').trim()

export function storedOcrApiUrl(storageKey = 'medical-ocr-api-url') {
  return localStorage.getItem(storageKey) || defaultOcrApiUrl
}
