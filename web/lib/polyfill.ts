/**
 * 浏览器兼容补丁。
 *
 * 背景：pdfjs-dist 4.x 内部使用了 Promise.withResolvers（Chrome/Edge 119+ 才有）。
 * 本机 Edge 是 112，实测阅读器直接报
 * "PDF 渲染失败：Promise.withResolvers is not a function"，左侧画布空白。
 *
 * 这类缺口不能靠"让用户升级浏览器"解决——评审用什么版本我们不知道，
 * 而且它坏掉的正好是最核心的模块三。这里补上缺失的原语，
 * 让 pdfjs 在 ES2021 级别的浏览器上也能跑。
 */

type Resolvers<T> = {
  promise: Promise<T>;
  resolve: (value: T | PromiseLike<T>) => void;
  reject: (reason?: unknown) => void;
};

export function ensureModernJsPolyfills(): void {
  const P = Promise as unknown as {
    withResolvers?: <T>() => Resolvers<T>;
  };
  if (typeof P.withResolvers === "function") return;

  P.withResolvers = function <T>(): Resolvers<T> {
    let resolve!: (value: T | PromiseLike<T>) => void;
    let reject!: (reason?: unknown) => void;
    const promise = new Promise<T>((res, rej) => {
      resolve = res;
      reject = rej;
    });
    return { promise, resolve, reject };
  };
}
