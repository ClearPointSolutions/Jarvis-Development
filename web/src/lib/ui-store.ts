import { create } from "zustand";

interface UiState {
  eventFilter: string;
  selectedNodeId: string | null;
  sidebarOpen: boolean;
  closeSidebar: () => void;
  setEventFilter: (filter: string) => void;
  setSelectedNodeId: (nodeId: string | null) => void;
  toggleSidebar: () => void;
}

export const useUiStore = create<UiState>((set) => ({
  eventFilter: "all",
  selectedNodeId: null,
  sidebarOpen: false,
  closeSidebar: () => set({ sidebarOpen: false }),
  setEventFilter: (eventFilter) => set({ eventFilter }),
  setSelectedNodeId: (selectedNodeId) => set({ selectedNodeId }),
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
}));
