interface Props {
  side: 'left' | 'right'
  currentWidth: number
  onResize: (width: number) => void
}

export function ResizeHandle({ side, currentWidth, onResize }: Props) {
  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault()
    const startX = e.clientX
    const startWidth = currentWidth

    const onMouseMove = (ev: MouseEvent) => {
      const diff = side === 'left' ? ev.clientX - startX : startX - ev.clientX
      const newWidth = Math.max(side === 'left' ? 180 : 320, startWidth + diff)
      onResize(newWidth)
    }

    const onMouseUp = () => {
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
    }

    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
  }

  return (
    <div
      onMouseDown={handleMouseDown}
      className="w-px cursor-col-resize bg-gray-200 hover:bg-teal-500 hover:w-0.5 transition-all shrink-0 relative"
    >
      <div className="absolute inset-y-0 -left-1.5 -right-1.5" />
    </div>
  )
}
