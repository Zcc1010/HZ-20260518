const API = '/api/wave-record-workspace'

export interface FileNode {
  name: string
  path: string
  type: 'file' | 'directory'
  size?: number
  mtime?: string
  children?: FileNode[]
}

// ── Workspace ──

export async function listWorkspaces(): Promise<string[]> {
  const r = await fetch(`${API}/workspaces`)
  const data = await r.json()
  return (data.items || []).map((i: any) => i.name)
}

export async function createWorkspace(name: string): Promise<void> {
  await fetch(`${API}/workspaces`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
}

export async function renameWorkspace(ws: string, newName: string): Promise<void> {
  await fetch(`${API}/workspaces/${encodeURIComponent(ws)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: newName }),
  })
}

export async function deleteWorkspace(ws: string): Promise<void> {
  await fetch(`${API}/workspaces/${encodeURIComponent(ws)}`, { method: 'DELETE' })
}

// ── Files ──

export async function getFileTree(ws: string): Promise<FileNode[]> {
  const r = await fetch(`${API}/workspaces/${encodeURIComponent(ws)}/tree`)
  return r.json()
}

export async function searchFiles(ws: string, q: string): Promise<{ name: string; path: string }[]> {
  const r = await fetch(`${API}/workspaces/${encodeURIComponent(ws)}/search?q=${encodeURIComponent(q)}`)
  const data = await r.json()
  return data.items || []
}

export interface BinaryFileData {
  base64: string
  name: string
  ext: string
}

export function getFileUrl(ws: string, filePath: string): string {
  return `${API}/workspaces/${encodeURIComponent(ws)}/read?path=${encodeURIComponent(filePath)}`
}

export async function readBinaryFile(ws: string, filePath: string): Promise<BinaryFileData> {
  const r = await fetch(getFileUrl(ws, filePath))
  return r.json()
}

export async function writeFile(ws: string, filePath: string, content: string): Promise<void> {
  await fetch(`${API}/workspaces/${encodeURIComponent(ws)}/write`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: filePath, content }),
  })
}

export async function renameFile(ws: string, filePath: string, newName: string): Promise<void> {
  await fetch(`${API}/workspaces/${encodeURIComponent(ws)}/rename`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: filePath, newName }),
  })
}

export async function copyFile(ws: string, src: string, dest: string): Promise<void> {
  await fetch(`${API}/workspaces/${encodeURIComponent(ws)}/copy`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ src, dest }),
  })
}

export async function duplicateFile(ws: string, filePath: string): Promise<void> {
  await fetch(`${API}/workspaces/${encodeURIComponent(ws)}/duplicate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: filePath }),
  })
}

export async function moveFile(ws: string, src: string, dest: string): Promise<void> {
  await fetch(`${API}/workspaces/${encodeURIComponent(ws)}/move`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ src, dest }),
  })
}

export async function deleteFile(ws: string, filePath: string): Promise<void> {
  await fetch(`${API}/workspaces/${encodeURIComponent(ws)}/file?path=${encodeURIComponent(filePath)}`, {
    method: 'DELETE',
  })
}

export async function uploadFiles(ws: string, files: File[]): Promise<string[]> {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  const r = await fetch(`${API}/workspaces/${encodeURIComponent(ws)}/upload`, {
    method: 'POST',
    body: form,
  })
  const data = await r.json()
  return data.files || []
}
