import { useEffect, useRef, useState } from "react";

function getWebSocketUrl(path) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${path}`;
}

export default function useJobSocket({ onMessage } = {}) {
  const socketRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const onMessageRef = useRef(onMessage);
  const connectionIdRef = useRef(0);

  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState(null);
  const [socketUrl, setSocketUrl] = useState("");

  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    let closedByComponent = false;

    function isCurrentConnection(connectionId) {
      return connectionIdRef.current === connectionId;
    }

    function connect() {
      connectionIdRef.current += 1;
      const connectionId = connectionIdRef.current;
      const url = getWebSocketUrl("/ws/jobs/");
      setSocketUrl(url);

      const socket = new WebSocket(url);
      socketRef.current = socket;

      socket.onopen = () => {
        if (!isCurrentConnection(connectionId)) return;
        setConnected(true);
        setLastMessage({ type: "socket_open", message: "WebSocket connection opened." });
        socket.send(JSON.stringify({ type: "ping" }));
      };

      socket.onmessage = (event) => {
        if (!isCurrentConnection(connectionId)) return;
        try {
          const data = JSON.parse(event.data);
          setLastMessage(data);
          onMessageRef.current?.(data);
        } catch {
          setLastMessage({ type: "raw", message: event.data });
        }
      };

      socket.onclose = (event) => {
        if (!isCurrentConnection(connectionId)) return;
        setConnected(false);
        setLastMessage({
          type: "socket_closed",
          message: "WebSocket connection closed.",
          code: event.code,
          reason: event.reason || "",
        });
        if (!closedByComponent) {
          reconnectTimerRef.current = window.setTimeout(connect, 3000);
        }
      };

      socket.onerror = () => {
        if (!isCurrentConnection(connectionId)) return;
        setConnected(false);
        setLastMessage({
          type: "socket_error",
          message: "WebSocket error. Check the OpenLIMS web proxy and ASGI service.",
        });
      };
    }

    connect();

    return () => {
      closedByComponent = true;
      connectionIdRef.current += 1;
      if (reconnectTimerRef.current) window.clearTimeout(reconnectTimerRef.current);
      if (socketRef.current) socketRef.current.close();
    };
  }, []);

  return { connected, lastMessage, socketUrl };
}
