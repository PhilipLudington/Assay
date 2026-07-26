import type { ApiRequest } from './request.js';
import type { ApiResponse } from './response.js';

export type Handler = (request: ApiRequest, response: ApiResponse) => Promise<void> | void;
export type Middleware = (
  request: ApiRequest,
  response: ApiResponse,
  next: () => Promise<void>,
) => Promise<void>;

interface Route {
  method: string;
  segments: string[];
  handler: Handler;
}

export class Router {
  private readonly routes: Route[] = [];
  private readonly middleware: Middleware[] = [];

  use(middleware: Middleware): this {
    this.middleware.push(middleware);
    return this;
  }

  add(method: string, pattern: string, handler: Handler): this {
    this.routes.push({
      method: method.toUpperCase(),
      segments: pattern.split('/').filter(Boolean),
      handler,
    });
    return this;
  }

  get = (pattern: string, handler: Handler) => this.add('GET', pattern, handler);
  post = (pattern: string, handler: Handler) => this.add('POST', pattern, handler);
  patch = (pattern: string, handler: Handler) => this.add('PATCH', pattern, handler);
  delete = (pattern: string, handler: Handler) => this.add('DELETE', pattern, handler);

  match(method: string, path: string): { handler: Handler; params: Record<string, string> } | undefined {
    const parts = path.split('/').filter(Boolean);
    for (const route of this.routes) {
      if (route.method !== method.toUpperCase() || route.segments.length !== parts.length) {
        continue;
      }
      const params: Record<string, string> = {};
      let matched = true;
      for (const [index, segment] of route.segments.entries()) {
        const actual = parts[index] as string;
        if (segment.startsWith(':')) {
          params[segment.slice(1)] = decodeURIComponent(actual);
        } else if (segment !== actual) {
          matched = false;
          break;
        }
      }
      if (matched) {
        return { handler: route.handler, params };
      }
    }
    return undefined;
  }

  async dispatch(request: ApiRequest, response: ApiResponse, terminal: Handler): Promise<void> {
    let index = -1;
    const run = async (): Promise<void> => {
      index += 1;
      const middleware = this.middleware[index];
      if (middleware) {
        await middleware(request, response, run);
        return;
      }
      await terminal(request, response);
    };
    await run();
  }
}
