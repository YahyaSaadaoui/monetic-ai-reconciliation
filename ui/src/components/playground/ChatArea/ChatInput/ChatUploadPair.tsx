'use client'
import { useRef } from 'react'
import { Button } from '@/components/ui/button'
import Icon from '@/components/ui/icon'
import { toast } from 'sonner'

export default function ChatUploadPair() {
  const fileRef = useRef<HTMLInputElement>(null)
  const endpoint = 'http://127.0.0.1:7788/reconcile'

  const onPick = () => fileRef.current?.click()

  const onChange: React.ChangeEventHandler<HTMLInputElement> = async (e) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    const isArchive = (f: File) => /\.(zip|rar)$/i.test(f.name)

    // Enforce: exactly two non-archive files OR exactly one archive file
    if (files.length === 1 && isArchive(files[0])) {
      // ok
    } else if (files.length === 2 && !isArchive(files[0]) && !isArchive(files[1])) {
      // ok
    } else {
      toast.error('Upload exactly two files (issuer + acquirer), or a single .zip/.rar')
      if (fileRef.current) fileRef.current.value = ''
      return
    }

    try {
      const form = new FormData()
      for (const f of Array.from(files)) form.append('files', f)
      const res = await fetch(endpoint, { method: 'POST', body: form })
      const data = await res.json()
      if (!res.ok) throw new Error(data?.detail || 'Upload failed')
      const mode = data.mode
      if (mode === 'pair') {
        const m = data.result.metrics
        toast.success(`Reconciliation done. Matches: ${m.matched}, mismatches: ${m.mismatches}, issuer-only: ${m.issuer_only}, acquirer-only: ${m.acquirer_only}`)
      } else {
        toast.success(`Archive processed. Pairs: ${data.result?.pairs ?? data.pairs}`)
      }
    } catch (e: any) {
      toast.error(e.message || String(e))
    } finally {
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div className="flex items-center gap-2">
      <input
        ref={fileRef}
        type="file"
        accept=".json,.csv,.xml,.zip,.rar"
        multiple
        className="hidden"
        onChange={onChange}
      />
      <Button type="button" onClick={onPick} className="rounded-xl bg-primary p-5 text-primaryAccent" title="Upload issuer+acquirer or an archive">
        <Icon type="download" color="primaryAccent" />
      </Button>
    </div>
  )
}
