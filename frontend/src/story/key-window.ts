// Turns the green glass in the window artwork into real transparency, in the browser,
// so the live sky can sit behind the frame. Runs once while the preloader is showing.

export interface GlassBounds {
    x: number
    y: number
    width: number
    height: number
}

const loadImage = (src: string): Promise<HTMLImageElement> => new Promise((resolve, reject) => {
    const image = new Image()
    image.decoding = 'async'
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('The window artwork could not be loaded'))
    image.src = src
})

const isKey = (r: number, g: number, b: number): boolean => g > 110 && g - r > 55 && g - b > 55

const clampByte = (value: number): number => (value < 0 ? 0 : value > 255 ? 255 : value)

export const drawKeyedWindow = async (
    src: string,
    canvas: HTMLCanvasElement,
    maxWidth = 2752
): Promise<GlassBounds> => {
    const image = await loadImage(src)
    const scale = Math.min(1, maxWidth / image.naturalWidth)
    const width = Math.round(image.naturalWidth * scale)
    const height = Math.round(image.naturalHeight * scale)

    canvas.width = width
    canvas.height = height

    const context = canvas.getContext('2d', { willReadFrequently: true })
    if (!context) throw new Error('Canvas is not available')

    context.drawImage(image, 0, 0, width, height)

    const frame = context.getImageData(0, 0, width, height)
    const data = frame.data
    const mask = new Uint8Array(width * height)

    // Find a seed pixel on the glass, starting from the middle of the frame
    const centreY = Math.round(height * 0.5)
    const centreX = Math.round(width * 0.5)
    let seed = -1

    for (let dx = 0; dx < width / 4 && seed < 0; dx += 1) {
        for (const x of [centreX + dx, centreX - dx]) {
            const index = centreY * width + x
            const offset = index * 4
            if (isKey(data[offset], data[offset + 1], data[offset + 2])) {
                seed = index
                break
            }
        }
    }

    if (seed < 0) throw new Error('The glass could not be found')

    // Flood fill only the connected glass, so nothing else in the picture is touched
    const stack = new Int32Array(width * height)
    let pointer = 0
    let minX = width
    let maxX = 0
    let minY = height
    let maxY = 0
    let keyR = 0
    let keyG = 0
    let keyB = 0
    let keyCount = 0

    stack[pointer++] = seed
    mask[seed] = 1

    while (pointer > 0) {
        const index = stack[--pointer]
        const x = index % width
        const y = (index - x) / width
        const offset = index * 4

        keyR += data[offset]
        keyG += data[offset + 1]
        keyB += data[offset + 2]
        keyCount += 1

        if (x < minX) minX = x
        if (x > maxX) maxX = x
        if (y < minY) minY = y
        if (y > maxY) maxY = y

        const neighbours = [
            x > 0 ? index - 1 : -1,
            x < width - 1 ? index + 1 : -1,
            y > 0 ? index - width : -1,
            y < height - 1 ? index + width : -1
        ]

        for (const next of neighbours) {
            if (next < 0 || mask[next]) continue
            const nextOffset = next * 4
            if (isKey(data[nextOffset], data[nextOffset + 1], data[nextOffset + 2])) {
                mask[next] = 1
                stack[pointer++] = next
            }
        }
    }

    keyR /= keyCount
    keyG /= keyCount
    keyB /= keyCount
    const keyExcess = Math.max(1, keyG - Math.max(keyR, keyB))

    const radius = 3
    const boxMinX = Math.max(0, minX - radius - 1)
    const boxMaxX = Math.min(width - 1, maxX + radius + 1)
    const boxMinY = Math.max(0, minY - radius - 1)
    const boxMaxY = Math.min(height - 1, maxY + radius + 1)

    const nearGlass = (x: number, y: number): boolean => {
        for (let oy = -radius; oy <= radius; oy += 1) {
            const row = y + oy
            if (row < 0 || row >= height) continue
            for (let ox = -radius; ox <= radius; ox += 1) {
                const column = x + ox
                if (column < 0 || column >= width) continue
                if (mask[row * width + column]) return true
            }
        }
        return false
    }

    for (let y = boxMinY; y <= boxMaxY; y += 1) {
        for (let x = boxMinX; x <= boxMaxX; x += 1) {
            const index = y * width + x
            const offset = index * 4

            if (mask[index]) {
                data[offset + 3] = 0
                continue
            }

            const r = data[offset]
            const g = data[offset + 1]
            const b = data[offset + 2]
            const excess = g - Math.max(r, b)
            if (excess <= 6 || !nearGlass(x, y)) continue

            // Un-mix the green from the edge pixels so the frame keeps a clean, soft edge
            const fraction = Math.min(1, excess / keyExcess)
            const keep = 1 - fraction

            if (keep < 0.04) {
                data[offset + 3] = 0
                continue
            }

            const cleanR = clampByte((r - fraction * keyR) / keep)
            const cleanB = clampByte((b - fraction * keyB) / keep)
            const cleanG = clampByte(Math.min((g - fraction * keyG) / keep, Math.max(cleanR, cleanB)))

            data[offset] = cleanR
            data[offset + 1] = cleanG
            data[offset + 2] = cleanB
            data[offset + 3] = Math.round(255 * keep)
        }
    }

    context.putImageData(frame, 0, 0)

    // Fade the outer edges into pure black so the frame melts into the stage
    context.globalCompositeOperation = 'source-atop'

    const edges: Array<[number, number, number, number, number, number, number, number]> = [
        [0, 0, 0, height * 0.08, 0, 0, width, height * 0.08],
        [0, height, 0, height * 0.92, 0, height * 0.92, width, height * 0.08],
        [0, 0, width * 0.05, 0, 0, 0, width * 0.05, height],
        [width, 0, width * 0.95, 0, width * 0.95, 0, width * 0.05, height]
    ]

    for (const [x0, y0, x1, y1, rx, ry, rw, rh] of edges) {
        const gradient = context.createLinearGradient(x0, y0, x1, y1)
        gradient.addColorStop(0, 'rgba(0, 0, 0, 1)')
        gradient.addColorStop(1, 'rgba(0, 0, 0, 0)')
        context.fillStyle = gradient
        context.fillRect(rx, ry, rw, rh)
    }

    context.globalCompositeOperation = 'source-over'

    return {
        x: minX / width,
        y: minY / height,
        width: (maxX - minX) / width,
        height: (maxY - minY) / height
    }
}
