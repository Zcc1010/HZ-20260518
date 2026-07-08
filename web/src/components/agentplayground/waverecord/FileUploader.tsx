import { useCallback, useState } from 'react'
import { useWaveformStore, type DeviceData } from './comtrade/store'
import { parseCfg } from './comtrade/cfg'
import { parseDat } from './comtrade/dat'
import { parseHdr } from './comtrade/hdr'
import { detectMutations } from './comtrade/mutation'
import { extractEvents } from './comtrade/event'
import { nanoid } from 'nanoid'
import { Upload, Loader2 } from 'lucide-react'

interface Props {
  onFilesLoaded?: () => void
}

export default function FileUploader({ onFilesLoaded }: Props) {
  const addDevice = useWaveformStore(s => s.addDevice)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const processFiles = useCallback(async (files: FileList | File[]) => {
    setLoading(true)
    setError(null)

    try {
      const fileArray = Array.from(files)

      // Group files by base name (without extension)
      const fileGroups = new Map<string, Map<string, File>>()
      for (const file of fileArray) {
        const name = file.name
        const lastDot = name.lastIndexOf('.')
        const baseName = lastDot > 0 ? name.substring(0, lastDot) : name
        const ext = lastDot > 0 ? name.substring(lastDot + 1).toLowerCase() : ''

        if (!fileGroups.has(baseName)) {
          fileGroups.set(baseName, new Map())
        }
        fileGroups.get(baseName)!.set(ext, file)
      }

      // Process each group
      for (const [baseName, extMap] of fileGroups) {
        const cfgFile = extMap.get('cfg')
        const datFile = extMap.get('dat')
        const hdrFile = extMap.get('hdr')

        if (!cfgFile) {
          console.warn(`Skipping ${baseName}: no .cfg file found`)
          continue
        }

        if (!datFile) {
          console.warn(`Skipping ${baseName}: no .dat file found`)
          continue
        }

        // Parse .cfg
        const cfgText = await cfgFile.text()
        const cfg = parseCfg(cfgText)

        // Parse .dat
        const datBuffer = await datFile.arrayBuffer()
        const datData = new Uint8Array(datBuffer)
        const isBinary = cfg.dataFileType === 'BINARY'
        const samples = parseDat(datData, cfg, isBinary)

        // Parse .hdr (optional)
        let hdrData = null
        if (hdrFile) {
          const hdrText = await hdrFile.text()
          hdrData = parseHdr(hdrText)
        }

        // Detect mutations for each analog channel
        const mutations = cfg.analogChannelInfo.map((_, i) =>
          detectMutations(samples, cfg, i)
        )

        // Extract digital events
        const digitalNames = cfg.digitalChannelInfo.map(ch => ch.name)
        const events = extractEvents(samples, digitalNames)

        // Determine device type
        const recDevId = cfg.recDevId.toLowerCase()
        const filePath = baseName.toLowerCase()
        let deviceType: DeviceData['deviceType'] = 'unknown'
        if (recDevId.includes('线路') || filePath.includes('line')) {
          deviceType = 'line'
        } else if (recDevId.includes('变压器') || filePath.includes('transformer')) {
          deviceType = 'transformer'
        } else if (recDevId.includes('母线') || filePath.includes('busbar')) {
          deviceType = 'busbar'
        }

        // Extract station and set name
        const station = cfg.stationName || baseName.split('_')[0] || '未知厂站'
        const setName = cfg.recDevId || baseName.split('_')[1] || '未知套别'

        const device: DeviceData = {
          id: nanoid(),
          station,
          setName,
          cfg,
          samples,
          hdrData,
          deviceType,
          mutations,
          events,
          fileName: cfgFile.name,
          filePath: baseName,
          voltage: '',
          protectionType: '',
          deviceName: cfg.recDevId,
          model: '',
          softwareVersion: '',
          timeOffsetMs: 0,
          alignmentRefMs: null,
        }

        addDevice(device)
      }

      onFilesLoaded?.()
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : String(err)
      setError(errMsg)
      console.error('Failed to process files:', err)
    } finally {
      setLoading(false)
    }
  }, [addDevice, onFilesLoaded])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    if (e.dataTransfer.files.length) {
      processFiles(e.dataTransfer.files)
    }
  }, [processFiles])

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.length) {
      processFiles(e.target.files)
      e.target.value = ''
    }
  }, [processFiles])

  return (
    <div
      className="border-2 border-dashed border-gray-200 rounded-lg p-6 text-center hover:border-teal-400 transition-colors cursor-pointer"
      onDragOver={(e) => e.preventDefault()}
      onDrop={handleDrop}
      onClick={() => document.getElementById('comtrade-file-input')?.click()}
    >
      <input
        id="comtrade-file-input"
        type="file"
        multiple
        accept=".cfg,.dat,.hdr"
        onChange={handleFileChange}
        className="hidden"
      />
      {loading ? (
        <div className="flex flex-col items-center gap-2">
          <Loader2 className="w-8 h-8 text-teal-500 animate-spin" />
          <span className="text-sm text-gray-500">正在解析文件...</span>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-2">
          <Upload className="w-8 h-8 text-gray-400" />
          <div className="text-sm text-gray-600">
            拖放 COMTRADE 文件到此处，或点击选择
          </div>
          <div className="text-xs text-gray-400">
            支持 .cfg / .dat / .hdr 文件
          </div>
        </div>
      )}
      {error && (
        <div className="mt-3 text-xs text-red-500 bg-red-50 px-3 py-1.5 rounded-md">
          {error}
        </div>
      )}
    </div>
  )
}
