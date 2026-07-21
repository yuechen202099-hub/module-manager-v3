export function createConstructionPriorityImportSession() {
  let generation = 0

  return {
    begin() {
      generation += 1
      return generation
    },
    capture() {
      return generation
    },
    invalidate() {
      generation += 1
    },
    isCurrent(token) {
      return token === generation
    },
  }
}

function dispositionParameter(disposition, name) {
  const match = String(disposition || '').match(new RegExp(`(?:^|;)\\s*${name}\\s*=\\s*(?:"([^"]*)"|([^;]*))`, 'i'))
  return (match?.[1] ?? match?.[2] ?? '').trim()
}

export function parseContentDispositionFilename(disposition, fallbackName) {
  const encoded = dispositionParameter(disposition, 'filename\\*')
  if (encoded) {
    const encodedMatch = encoded.match(/^utf-8'[^']*'(.*)$/i)
    if (encodedMatch?.[1]) {
      try {
        return decodeURIComponent(encodedMatch[1])
      } catch {
        // Fall through to the ordinary filename parameter.
      }
    }
  }

  return dispositionParameter(disposition, 'filename') || fallbackName
}
