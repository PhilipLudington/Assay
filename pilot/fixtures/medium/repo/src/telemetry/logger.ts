export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

const ORDER: Record<LogLevel, number> = { debug: 10, info: 20, warn: 30, error: 40 };

export interface Logger {
  log(level: LogLevel, message: string, fields?: Record<string, unknown>): void;
}

export class ConsoleLogger implements Logger {
  constructor(private readonly minLevel: LogLevel = 'info') {}

  log(level: LogLevel, message: string, fields: Record<string, unknown> = {}): void {
    if (ORDER[level] < ORDER[this.minLevel]) {
      return;
    }
    const line = JSON.stringify({ level, message, ...fields });
    if (level === 'error' || level === 'warn') {
      process.stderr.write(`${line}\n`);
    } else {
      process.stdout.write(`${line}\n`);
    }
  }
}

export class NullLogger implements Logger {
  log(): void {
    // discard
  }
}

export const nullLogger = new NullLogger();
