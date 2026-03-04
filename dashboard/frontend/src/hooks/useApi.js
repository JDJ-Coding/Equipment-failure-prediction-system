import { useState, useCallback } from 'react'
import axios from 'axios'

const BASE = '/api'

export function useApi() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const request = useCallback(async (method, path, payload = null, config = {}) => {
    setLoading(true)
    setError(null)
    try {
      const res = await axios({ method, url: BASE + path, data: payload, ...config })
      return res.data
    } catch (err) {
      const msg = err.response?.data?.detail || err.message
      setError(msg)
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  const get  = (path, params) => request('get',  path, null, { params })
  const post = (path, data, cfg) => request('post', path, data, cfg)

  return { get, post, loading, error }
}
