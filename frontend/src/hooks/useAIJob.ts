import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { AIJob, FormatId } from "../types";

export const isActiveJob = (job: AIJob | null | undefined) =>
  !!job && (job.status === "queued" || job.status === "running");

/**
 * Follows a server-side AI job: reattaches to an active one after a reload and
 * polls until it finishes, then calls `onFinish` once with the final state.
 */
export function useAIJob(
  formatId: FormatId,
  kind: AIJob["kind"],
  onFinish: (job: AIJob) => void,
) {
  const [job, setJob] = useState<AIJob | null>(null);
  const finish = useRef(onFinish);
  finish.current = onFinish;

  useEffect(() => {
    let stopped = false;
    api
      .listAIJobs(formatId, kind)
      .then((r) => {
        const active = r.jobs.find(isActiveJob);
        if (!stopped && active) setJob(active);
      })
      .catch(() => {});
    return () => {
      stopped = true;
    };
  }, [formatId, kind]);

  useEffect(() => {
    if (!job || !isActiveJob(job)) return;
    const timer = setTimeout(async () => {
      try {
        const next = await api.getAIJob(job.id);
        setJob(next);
        if (!isActiveJob(next)) finish.current(next);
      } catch {
        setJob({ ...job }); // transient error: poll again
      }
    }, 2000);
    return () => clearTimeout(timer);
  }, [job]);

  return [job, setJob] as const;
}
