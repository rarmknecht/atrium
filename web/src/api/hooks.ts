import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export const keys = {
  modules: ["modules"] as const,
  module: (id: string) => ["modules", id] as const,
  runs: (id: string) => ["runs", id] as const,
  recentRuns: ["runs", "recent"] as const,
  triggers: (id?: string) => ["triggers", id ?? "all"] as const,
  reports: (p: object) => ["reports", p] as const,
  tree: ["context", "tree"] as const,
  doc: (path: string) => ["context", "doc", path] as const,
  graph: ["context", "graph"] as const,
  settings: ["settings"] as const,
};

export const useModules = () => useQuery({ queryKey: keys.modules, queryFn: api.listModules });
export const useModule = (id: string) =>
  useQuery({ queryKey: keys.module(id), queryFn: () => api.getModule(id) });
export const useRuns = (id: string) =>
  useQuery({ queryKey: keys.runs(id), queryFn: () => api.listRuns(id) });
export const useRecentRuns = () =>
  useQuery({ queryKey: keys.recentRuns, queryFn: () => api.recentRuns(30) });
export const useTriggers = (moduleId?: string) =>
  useQuery({ queryKey: keys.triggers(moduleId), queryFn: () => api.listTriggers(moduleId) });
export const useReports = (p: { module_id?: string; kind?: string } = {}) =>
  useQuery({ queryKey: keys.reports(p), queryFn: () => api.listReports(p) });
export const useTree = () => useQuery({ queryKey: keys.tree, queryFn: api.contextTree });
export const useGraph = () => useQuery({ queryKey: keys.graph, queryFn: api.graph });
export const useSettings = () => useQuery({ queryKey: keys.settings, queryFn: api.settings });
export const useDoc = (path: string | null) =>
  useQuery({
    queryKey: keys.doc(path ?? ""),
    queryFn: () => api.getDoc(path as string),
    enabled: !!path,
  });

export function useRunModule(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.runModule(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.runs(id) });
      qc.invalidateQueries({ queryKey: keys.recentRuns });
      qc.invalidateQueries({ queryKey: ["reports"] });
    },
  });
}

export function useSaveConfig(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (config: Record<string, unknown>) => api.saveConfig(id, config),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.module(id) }),
  });
}

export function useSetEnabled(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) => api.setEnabled(id, enabled),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.module(id) });
      qc.invalidateQueries({ queryKey: keys.modules });
    },
  });
}

export function useTriggerMutations(moduleId: string) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: keys.triggers(moduleId) });
  return {
    create: useMutation({ mutationFn: api.createTrigger, onSuccess: invalidate }),
    update: useMutation({
      mutationFn: (v: { id: string; body: { config?: Record<string, unknown>; enabled?: boolean } }) =>
        api.updateTrigger(v.id, v.body),
      onSuccess: invalidate,
    }),
    remove: useMutation({ mutationFn: api.deleteTrigger, onSuccess: invalidate }),
  };
}

export function useDocMutations() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: keys.tree });
    qc.invalidateQueries({ queryKey: keys.graph });
  };
  return {
    save: useMutation({
      mutationFn: api.putDoc,
      onSuccess: (doc) => {
        invalidate();
        qc.invalidateQueries({ queryKey: keys.doc(doc.path) });
      },
    }),
    remove: useMutation({ mutationFn: api.deleteDoc, onSuccess: invalidate }),
    reindex: useMutation({ mutationFn: api.reindex, onSuccess: invalidate }),
  };
}
