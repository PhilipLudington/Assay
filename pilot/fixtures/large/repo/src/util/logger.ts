export type Level = 'debug' | 'info' | 'warn' | 'error';

const RANK: Record<Level, number> = { debug: 10, info: 20, warn: 30, error: 40 };

export interface Logger {
  child(fields: Record<string, unknown>): Logger;
  log(level: Level, message: string, fields?: Record<string, unknown>): void;
}

export class JsonLogger implements Logger {
  constructor(
    private readonly minLevel: Level = 'info',
    private readonly base: Record<string, unknown> = {},
  ) {}

  child(fields: Record<string, unknown>): Logger {
    return new JsonLogger(this.minLevel, { ...this.base, ...fields });
  }

  log(level: Level, message: string, fields: Record<string, unknown> = {}): void {
    if (RANK[level] < RANK[this.minLevel]) {
      return;
    }
    const stream = RANK[level] >= RANK.warn ? process.stderr : process.stdout;
    stream.write(`${JSON.stringify({ level, message, ...this.base, ...fields })}\n`);
  }
}

export const rootLogger: Logger = new JsonLogger();
