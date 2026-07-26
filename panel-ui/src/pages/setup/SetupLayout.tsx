import { Outlet } from 'react-router-dom'

// The hosting-provider admin console. Navigation lives in the main nav as an
// expandable "Setup" dropdown (see Shell.tsx); each page renders here in the
// app's admin-console content width.
export function SetupLayout() {
  return (
    <div className="max-w-4xl mx-auto">
      <Outlet />
    </div>
  )
}
