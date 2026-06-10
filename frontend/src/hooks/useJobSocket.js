import { useEffect, useRef, useState } from "react";

function getStoredAccessToken() {
  return (
    localStorage.getItem("openlims_access") ||
    localStorage.getItem("access") ||
    localStorage.getItem("access_token") ||
    localStorage.getItem("token") ||
    sessionStorage.getItem("access") ||
    sessionStorage.getItem("access_token") ||
    sessionStorage.getItem("token")
  );
}

function getWebSocketUrl(path) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const token = getStoredAccessToken();
  const query = token ? `?token=${encodeURIComponent(token)}` : "";

  const isLocalDev =
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1";

  const host = isLocalDev ? "localhost:8000" : window.location.host;

  return `${protocol}//${host}${path}${query}`;
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
      const token = getStoredAccessToken();

      if (!token) {
        setConnected(false);
        setLastMessage({
          type: "error",
          message:
            "No JWT access token found. Log in again, then return to this page.",
        });
        return;
      }

      connectionIdRef.current += 1;
      const connectionId = connectionIdRef.current;

      const url = getWebSocketUrl("/ws/jobs/");
      setSocketUrl(url.replace(token, "[token-hidden]"));

      const socket = new WebSocket(url);
      socketRef.current = socket;

      socket.onopen = () => {
        if (!isCurrentConnection(connectionId)) return;

        setConnected(true);
        setLastMessage({
          type: "socket_open",
          message: "WebSocket connection opened.",
        });

        socket.send(
          JSON.stringify({
            type: "ping",
          })
        );
      };

      socket.onmessage = (event) => {
        if (!isCurrentConnection(connectionId)) return;

        try {
          const data = JSON.parse(event.data);
          setLastMessage(data);

          if (onMessageRef.current) {
            onMessageRef.current(data);
          }
        } catch {
          setLastMessage({
            type: "raw",
            message: event.data,
          });
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
          message:
            "WebSocket error. Check that Daphne is running and /ws/jobs/ exists.",
        });
      };
    }

    connect();

    return () => {
      closedByComponent = true;
      connectionIdRef.current += 1;

      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
      }

      if (socketRef.current) {
        socketRef.current.close();
      }
    };
  }, []);

  return {
    connected,
    lastMessage,
    socketUrl,
  };
}
