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

export function createMutationGuardedRequestGate(setLoading = () => {}) {
  const latest = createLatestRequestGate(setLoading)
  let serial = 0

  return {
    begin(mutationVersion = 0) {
      const request = latest.begin()
      const requestSerial = ++serial
      const requestMutationVersion = Number(mutationVersion || 0)
      return {
        signal: request.signal,
        serial: requestSerial,
        mutationVersion: requestMutationVersion,
        isCurrent(currentMutationVersion) {
          return request.isCurrent() && Number(currentMutationVersion || 0) === requestMutationVersion
        },
        finish() {
          request.finish()
        },
      }
    },
    invalidate() {
      latest.cancel()
    },
    cancel() {
      latest.cancel()
    },
  }
}
