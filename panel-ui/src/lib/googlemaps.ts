// Minimal, dependency-free Google Maps JS SDK loader — the same vanilla-SDK
// approach the Pinpoint app uses (loaded via a <script> tag), with the promise
// dedupe the app never centralized. The panel never imports @react-google-maps;
// it just needs the `google.maps` global.

/* eslint-disable @typescript-eslint/no-explicit-any */
declare global {
  interface Window {
    google?: any
    __ppMapsInit?: () => void
  }
}

let loadingPromise: Promise<void> | null = null

/** Load the Maps JS SDK once. Resolves when `window.google.maps` is ready. */
export function loadGoogleMaps(apiKey: string): Promise<void> {
  if (typeof window === 'undefined') return Promise.reject(new Error('no window'))
  if (window.google?.maps) return Promise.resolve()
  if (loadingPromise) return loadingPromise
  loadingPromise = new Promise<void>((resolve, reject) => {
    const script = document.createElement('script')
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(
      apiKey,
    )}&libraries=places&loading=async&callback=__ppMapsInit`
    script.async = true
    script.defer = true
    window.__ppMapsInit = () => {
      resolve()
      delete window.__ppMapsInit
    }
    script.onerror = () => {
      loadingPromise = null
      reject(new Error('Failed to load Google Maps'))
    }
    document.head.appendChild(script)
  })
  return loadingPromise
}

/** Extend a LatLngBounds with every vertex of a Data-layer feature. */
export function extendBoundsFromFeature(bounds: any, feature: any) {
  const geom = feature.getGeometry?.()
  if (geom) geom.forEachLatLng((ll: any) => bounds.extend(ll))
}
