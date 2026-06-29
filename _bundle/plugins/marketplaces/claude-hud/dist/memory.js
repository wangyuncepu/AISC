import os from 'node:os';
let readMemory = () => ({
    totalBytes: os.totalmem(),
    freeBytes: os.freemem(),
});
export async function getMemoryUsage() {
    try {
        const { totalBytes, freeBytes } = readMemory();
        if (!Number.isFinite(totalBytes) || totalBytes <= 0) {
            return null;
        }
        const safeFreeBytes = Number.isFinite(freeBytes)
            ? Math.min(Math.max(freeBytes, 0), totalBytes)
            : 0;
        const usedBytes = totalBytes - safeFreeBytes;
        const usedPercent = Math.round((usedBytes / totalBytes) * 100);
        return {
            totalBytes,
            usedBytes,
            freeBytes: safeFreeBytes,
            usedPercent: Math.min(Math.max(usedPercent, 0), 100),
        };
    }
    catch {
        return null;
    }
}
export function formatBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) {
        return '0 B';
    }
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let value = bytes;
    let unitIndex = 0;
    while (value >= 1024 && unitIndex < units.length - 1) {
        value /= 1024;
        unitIndex += 1;
    }
    const fractionDigits = value >= 10 || unitIndex === 0 ? 0 : 1;
    return `${value.toFixed(fractionDigits)} ${units[unitIndex]}`;
}
export function _setMemoryReaderForTests(reader) {
    readMemory = reader ?? (() => ({
        totalBytes: os.totalmem(),
        freeBytes: os.freemem(),
    }));
}
//# sourceMappingURL=memory.js.map