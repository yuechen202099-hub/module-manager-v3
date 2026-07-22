export function isAbortError(error) {
  return Boolean(error && typeof error === 'object' && error.name === 'AbortError')
}

export function createLatestRequestGate(setLoading = () => {}) {
  let epoch = 0
  let controller = null

  function cancel() {
    epoch += 1
    if (!controller) return
    controller.abort()
    controller = null
    setLoading(false)
  }

  function begin() {
    controller?.abort()
    const requestEpoch = ++epoch
    const requestController = new AbortController()
    controller = requestController
    setLoading(true)

    const isCurrent = () => epoch === requestEpoch && controller === requestController
    return {
      signal: requestController.signal,
      isCurrent,
      finish() {
        if (!isCurrent()) return
        controller = null
        setLoading(false)
      },
    }
  }

  return { begin, cancel }
}
