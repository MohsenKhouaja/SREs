"use client";

import {useEffect, useState} from "react";
import {API_URL} from "./api";
import type {StreamEvent} from "./types";

export function useInvestigationStream(id?: string, enabled = true) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!id || !enabled) return;
    const source = new EventSource(`${API_URL}/stream/investigation/${id}`);
    source.onopen = () => setConnected(true);
    source.onmessage = (message) => {
      const event = JSON.parse(message.data) as StreamEvent;
      setEvents((current) => [...current.slice(-199), event]);
    };
    source.onerror = () => setConnected(false);
    return () => source.close();
  }, [id, enabled]);

  return {events, connected: enabled && connected};
}
