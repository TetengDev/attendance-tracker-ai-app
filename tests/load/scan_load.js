import ws from 'k6/ws';
import { check } from 'k6';

/**
 * k6 load test scenario to verify WebSocket scan loop under concurrent load.
 * Simulates multiple concurrent kiosk connections submitting scans and matching.
 */
export const options = {
  stages: [
    { duration: '10s', target: 50 }, // Ramp up to 50 concurrent connections
    { duration: '15s', target: 50 }, // Hold load at 50 connections
    { duration: '5s', target: 0 },   // Ramp down
  ],
  thresholds: {
    'ws_connecting': ['p(95)<500'], // 95% of connections must be established in <500ms
  },
};

export default function () {
  const url = 'ws://localhost:8000/ws/scan';

  const res = ws.connect(url, null, function (socket) {
    socket.on('open', () => {
      // Simulate client device pairing handshake
      socket.send(JSON.stringify({
        type: 'handshake',
        payload: {
          device_token: '14d75b41-d558-4a73-9369-93f32ef86a70'
        }
      }));
    });

    socket.on('message', (data) => {
      const msg = JSON.parse(data);
      check(msg, {
        'message is non-empty': (m) => m !== null,
        'message has event type': (m) => m.type !== undefined,
      });
      
      // Simulate checking-in scanning loop
      if (msg.type === 'handshake_ok') {
        socket.send(JSON.stringify({
          type: 'scan_frame',
          payload: {
            // Mock empty frame payload
            frame_b64: 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
            timestamp: new Date().toISOString()
          }
        }));
      }

      // Close the socket loop once a match or reject decision is made
      if (msg.type === 'match_success' || msg.type === 'match_failed') {
        socket.close();
      }
    });

    socket.on('error', (e) => {
      console.error('WebSocket error:', e.error());
    });
  });

  check(res, { 'successful connection': (r) => r && r.status === 101 });
}
