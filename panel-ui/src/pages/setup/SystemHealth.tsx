import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
    Server, Database, RefreshCw, HardDrive, Clock, Loader2,
    CheckCircle, XCircle, Shield, Cloud, Activity, AlertTriangle, ScrollText, KeyRound,
} from 'lucide-react'
import { Card, Button } from '../../components/ui'
import { api } from '../../lib/api'
import type { SystemHealth as Health, ProactiveHealth, UptimeStats, UptimeHistory } from '../../lib/types'

/**
 * System Health — the app's OperationsPanel, ported to the control plane.
 * Same structure and visual language (summary cards, proactive leading-
 * indicator block, service/integration grids, status badges); the data comes
 * from /api/system/health + /api/system/proactive instead of the app's
 * infrastructure runbooks, which the control plane doesn't have.
 */

// Verbatim from the app's OperationsPanel.
const getStatusBadge = (status: string) => {
    const colors: Record<string, string> = {
        running: 'bg-green-500/20 text-green-300 border-green-500/30',
        healthy: 'bg-green-500/20 text-green-300 border-green-500/30',
        configured: 'bg-green-500/20 text-green-300 border-green-500/30',
        stopped: 'bg-red-500/20 text-red-300 border-red-500/30',
        error: 'bg-red-500/20 text-red-300 border-red-500/30',
        unknown: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30',
        not_configured: 'bg-gray-500/20 text-gray-300 border-gray-500/30',
        disabled: 'bg-gray-500/20 text-gray-300 border-gray-500/30',
        fallback: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30',
    }
    return colors[status] || colors.unknown
}

const CHECK_ICON: Record<string, typeof Database> = {
    database: Database,
    secret_encryption: KeyRound,
    audit_chain: ScrollText,
}
const CHECK_LABEL: Record<string, string> = {
    database: 'Database',
    secret_encryption: 'Secret Encryption',
    audit_chain: 'Audit Chain',
}

export function SystemHealth() {
    const [health, setHealth] = useState<Health | null>(null)
    const [proactive, setProactive] = useState<ProactiveHealth | null>(null)
    const [uptimeStats, setUptimeStats] = useState<UptimeStats | null>(null)
    const [uptimeHistory, setUptimeHistory] = useState<UptimeHistory | null>(null)
    const [isLoading, setIsLoading] = useState(false)
    const [uptimeCheckLoading, setUptimeCheckLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const fetchAll = async () => {
        setIsLoading(true)
        setError(null)
        try {
            // Each source is fetched independently and tolerant of failure, so one
            // failing probe degrades that section instead of blanking the panel.
            const [healthData, proactiveData, statsData, historyData] = await Promise.all([
                api.systemHealth().catch(() => null),
                api.systemProactive().catch(() => null),
                api.getUptimeStats().catch(() => null),
                api.getUptimeHistory(48).catch(() => null),
            ])
            setHealth(healthData)
            setProactive(proactiveData)
            setUptimeStats(statsData)
            setUptimeHistory(historyData)
            if (!healthData && !proactiveData && !statsData && !historyData) {
                setError('Failed to fetch system status')
            }
        } catch (err: any) {
            setError(err?.message || 'Failed to fetch system status')
        } finally {
            setIsLoading(false)
        }
    }

    const triggerUptimeCheck = async () => {
        setUptimeCheckLoading(true)
        try {
            await api.triggerUptimeCheck()
            // Refresh data after check
            const [statsData, historyData] = await Promise.all([
                api.getUptimeStats().catch(() => null),
                api.getUptimeHistory(48).catch(() => null),
            ])
            setUptimeStats(statsData)
            setUptimeHistory(historyData)
        } catch (err) {
            console.error('Uptime check failed:', err)
        } finally {
            setUptimeCheckLoading(false)
        }
    }

    useEffect(() => {
        fetchAll()
        const interval = setInterval(fetchAll, 30000)
        return () => clearInterval(interval)
    }, [])

    if (error) {
        return (
            <Card className="bg-red-500/10 border-red-500/20">
                <div className="flex items-center gap-3">
                    <XCircle className="w-6 h-6 text-red-400" />
                    <div className="flex-1">
                        <h3 className="text-lg font-semibold text-red-300">Error Loading Dashboard</h3>
                        <p className="text-red-200/80 mt-1">{error}</p>
                    </div>
                    <Button onClick={fetchAll} disabled={isLoading}>
                        <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
                        Retry
                    </Button>
                </div>
            </Card>
        )
    }

    const checks = health ? Object.entries(health.checks) : []
    const passing = checks.filter(([, c]) => c.ok).length
    const loops = health?.background_loops || {}
    const enabledLoops = Object.values(loops).filter((v) => Number(v) > 0).length

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-xl font-bold text-white flex items-center gap-2">
                        <Activity className="w-6 h-6 text-blue-400" />
                        System Dashboard
                    </h2>
                    <p className="text-gray-300 text-sm mt-1">
                        Control-plane services, integrations, and early-warning checks
                    </p>
                </div>
                <Button onClick={fetchAll} disabled={isLoading} variant="secondary">
                    <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
                    Refresh
                </Button>
            </div>

            {/* Status Summary Cards */}
            {health && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <Card className={passing === checks.length ? 'bg-green-500/10 border-green-500/30' : 'bg-yellow-500/10 border-yellow-500/30'}>
                        <div className="flex items-center gap-3">
                            <Server className="w-8 h-8 text-blue-400" />
                            <div>
                                <p className="text-gray-300 text-xs uppercase tracking-wide">Control Plane</p>
                                <p className="text-white font-semibold">{passing}/{checks.length} Healthy</p>
                                <p className="text-gray-500 text-xs">v{health.version}</p>
                            </div>
                        </div>
                    </Card>

                    <Card className={health.checks.database?.ok ? 'bg-green-500/10 border-green-500/30' : 'bg-red-500/10 border-red-500/30'}>
                        <div className="flex items-center gap-3">
                            <Database className="w-8 h-8 text-purple-400" />
                            <div>
                                <p className="text-gray-300 text-xs uppercase tracking-wide">Database</p>
                                <p className="text-white font-semibold">{health.checks.database?.detail || '?'}</p>
                            </div>
                        </div>
                    </Card>

                    <Card className={health.checks.secret_encryption?.ok ? 'bg-green-500/10 border-green-500/30' : 'bg-yellow-500/10 border-yellow-500/30'}>
                        <div className="flex items-center gap-3">
                            <Shield className="w-8 h-8 text-orange-400" />
                            <div>
                                <p className="text-gray-300 text-xs uppercase tracking-wide">Encryption</p>
                                <p className="text-white font-semibold">{health.checks.secret_encryption?.detail || 'N/A'}</p>
                            </div>
                        </div>
                    </Card>

                    <Card className="bg-green-500/10 border-green-500/30">
                        <div className="flex items-center gap-3">
                            <Cloud className="w-8 h-8 text-purple-400" />
                            <div>
                                <p className="text-gray-300 text-xs uppercase tracking-wide">Fleet</p>
                                <p className="text-white font-semibold">{health.fleet.active}/{health.fleet.total} Active</p>
                                <p className="text-gray-500 text-xs">municipalities</p>
                            </div>
                        </div>
                    </Card>
                </div>
            )}

            {/* Proactive (leading-indicator) health — warns before something fails */}
            {proactive && (
                proactive.overall_status === 'ok' ? (
                    <Card className="bg-green-500/5 border-green-500/20">
                        <div className="flex items-center gap-3">
                            <CheckCircle className="w-5 h-5 text-green-400" />
                            <p className="text-green-200/90 text-sm font-medium">
                                All early-warning checks passing (disk, memory, database, backups, audit chain).
                            </p>
                        </div>
                    </Card>
                ) : (
                    <Card className={proactive.overall_status === 'critical' ? 'bg-red-500/5 border-red-500/30' : 'bg-amber-500/5 border-amber-500/30'}>
                        <h3 className={`text-lg font-semibold mb-1 flex items-center gap-2 ${proactive.overall_status === 'critical' ? 'text-red-300' : 'text-amber-300'}`}>
                            <AlertTriangle className="w-5 h-5" />
                            Needs attention {proactive.overall_status === 'critical' ? '— act now' : 'soon'}
                        </h3>
                        <p className="text-gray-400 text-xs mb-3">Leading indicators — resolving these prevents an outage. Off-host monitoring is alerted when a check crosses a threshold.</p>
                        <div className="space-y-2">
                            {proactive.checks
                                .filter(c => c.status === 'warning' || c.status === 'critical')
                                .map(c => (
                                    <div key={c.key} className="flex items-start gap-3 bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
                                        <span className={`px-2 py-0.5 mt-0.5 text-xs rounded-full border shrink-0 ${getStatusBadge(c.status === 'critical' ? 'error' : 'fallback')}`}>
                                            {c.status}
                                        </span>
                                        <div className="min-w-0">
                                            <p className="text-white text-sm font-medium">{c.label}: <span className="font-normal text-gray-300">{c.message}</span></p>
                                            {c.action && <p className="text-gray-400 text-xs mt-0.5">→ {c.action}</p>}
                                        </div>
                                    </div>
                                ))}
                        </div>
                    </Card>
                )
            )}

            {/* Uptime Monitoring */}
            <Card>
                <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-semibold text-white flex items-center gap-2">
                        <Clock className="w-5 h-5 text-green-400" />
                        Uptime Monitoring
                    </h3>
                    <Button
                        size="sm"
                        variant="secondary"
                        onClick={triggerUptimeCheck}
                        disabled={uptimeCheckLoading}
                    >
                        {uptimeCheckLoading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-2" />}
                        Check Now
                    </Button>
                </div>

                {/* Uptime Stats Cards */}
                {uptimeStats && Object.keys(uptimeStats.services).length > 0 ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 mb-4">
                        {Object.entries(uptimeStats.services).map(([serviceName, periods]) => (
                            <div key={serviceName} className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
                                <h4 className="text-white font-medium capitalize mb-2">{serviceName.replace(/_/g, ' ')}</h4>
                                <div className="grid grid-cols-3 gap-2">
                                    {(['24h', '7d', '30d'] as const).map(period => {
                                        const stats = periods[period]
                                        const pct = stats?.uptime_percent ?? 0
                                        const color = pct >= 99 ? 'text-green-400' : pct >= 95 ? 'text-yellow-400' : 'text-red-400'
                                        return (
                                            <div key={period} className="text-center">
                                                <p className={`text-lg font-bold ${color}`}>{pct.toFixed(1)}%</p>
                                                <p className="text-gray-500 text-xs">{period}</p>
                                            </div>
                                        )
                                    })}
                                </div>
                            </div>
                        ))}
                    </div>
                ) : (
                    <div className="text-gray-400 text-sm mb-4 p-4 bg-slate-800/30 rounded-lg text-center">
                        No uptime data yet. Click "Check Now" to start monitoring.
                    </div>
                )}

                {/* Uptime Timeline (last 48 hours) */}
                {uptimeHistory && Object.keys(uptimeHistory.services).length > 0 && (
                    <div className="space-y-3">
                        <p className="text-gray-400 text-xs">Last 48 hours (newest → oldest)</p>
                        {Object.entries(uptimeHistory.services).map(([serviceName, checks]) => (
                            <div key={serviceName} className="flex items-center gap-2">
                                <span className="text-white text-sm w-28 truncate capitalize">{serviceName.replace(/_/g, ' ')}</span>
                                <div className="flex-1 flex gap-0.5">
                                    {checks.slice(0, 48).map((check, idx) => (
                                        <div
                                            key={idx}
                                            className={`w-2 h-6 rounded-sm ${check.status === 'healthy' ? 'bg-green-500' :
                                                check.status === 'degraded' ? 'bg-yellow-500' : 'bg-red-500'
                                                }`}
                                            title={`${check.status} - ${new Date(check.checked_at).toLocaleString()}`}
                                        />
                                    ))}
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </Card>

            {/* Control-plane checks */}
            {health && (
                <Card>
                    <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                        <Shield className="w-5 h-5 text-purple-400" />
                        Control-Plane Checks
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        {checks.map(([key, c]) => {
                            const Icon = CHECK_ICON[key] || Database
                            return (
                                <div key={key} className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50">
                                    <div className="flex items-center gap-3 mb-2">
                                        <Icon className="w-5 h-5 text-blue-400" />
                                        <span className="text-white font-medium">{CHECK_LABEL[key] || key}</span>
                                        <span className={`ml-auto px-2 py-0.5 text-xs rounded-full border ${getStatusBadge(c.ok ? 'healthy' : 'error')}`}>
                                            {c.ok ? 'healthy' : 'error'}
                                        </span>
                                    </div>
                                    <p className="text-gray-300 text-xs">{c.detail}</p>
                                </div>
                            )
                        })}
                    </div>
                </Card>
            )}

            {/* Background loops */}
            {health && (
                <Card>
                    <div className="flex items-center justify-between mb-4">
                        <h3 className="text-lg font-semibold text-white flex items-center gap-2">
                            <Clock className="w-5 h-5 text-green-400" />
                            Background Loops
                        </h3>
                        <span className="text-gray-400 text-xs">{enabledLoops}/{Object.keys(loops).length} enabled</span>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                        {Object.entries(loops).map(([name, secs]) => (
                            <div key={name} className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
                                <div className="flex items-center justify-between mb-2">
                                    <span className="text-white font-medium capitalize">{name.replace(/_seconds$/, '').replace(/_/g, ' ')}</span>
                                    <span className={`px-2 py-0.5 text-xs rounded-full border ${getStatusBadge(Number(secs) > 0 ? 'running' : 'disabled')}`}>
                                        {Number(secs) > 0 ? 'running' : 'disabled'}
                                    </span>
                                </div>
                                <p className="text-gray-500 text-xs">
                                    {Number(secs) > 0 ? `every ${secs}s` : 'not scheduled'}
                                </p>
                            </div>
                        ))}
                    </div>
                </Card>
            )}

            {/* Loading State */}
            <AnimatePresence>
                {isLoading && !health && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                        className="flex items-center justify-center py-12">
                        <RefreshCw className="w-8 h-8 text-blue-400 animate-spin" />
                        <span className="ml-3 text-gray-300">Loading system dashboard...</span>
                    </motion.div>
                )}
            </AnimatePresence>

            {!isLoading && !health && !proactive && (
                <div className="flex items-center gap-3 text-gray-400 text-sm">
                    <HardDrive className="w-4 h-4" /> No system data available.
                </div>
            )}
        </div>
    )
}
