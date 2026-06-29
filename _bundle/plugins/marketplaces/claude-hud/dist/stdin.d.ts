import type { StdinData, UsageData } from './types.js';
export declare function readStdin(): Promise<StdinData | null>;
export declare function getTotalTokens(stdin: StdinData): number;
export declare function getContextPercent(stdin: StdinData): number;
export declare function getBufferedPercent(stdin: StdinData): number;
export declare function getModelName(stdin: StdinData): string;
export declare function isBedrockModelId(modelId?: string): boolean;
export declare function getProviderLabel(stdin: StdinData): string | null;
export declare function getUsageFromStdin(stdin: StdinData): UsageData | null;
//# sourceMappingURL=stdin.d.ts.map