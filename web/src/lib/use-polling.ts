import { useEffect } from "react";

/**
 * Run `load` now and then repeatedly. Each run waits for the last one to finish, so a slow response can't
 * overwrite a newer one, and hidden tabs make no requests.
 */
export function usePolling(load: () => Promise<void>, intervalMs: number) {
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;

    const run = async () => {
      if (!document.hidden) await load();
      if (!stopped) timer = setTimeout(run, intervalMs);
    };
    timer = setTimeout(run, 0);

    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [load, intervalMs]);
}
