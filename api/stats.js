export default function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();

  const now = new Date();
  const today = now.toISOString().split('T')[0];

  return res.status(200).json({
    ok: true,
    date: today,
    focus_minutes: 145,
    screen_time_min: 280,
    breaks_taken: 6,
    posture_alerts: 3,
    stress_minutes: 12,
    intruder_alerts: 0,
    pc_locks: 2,
    timestamp: now.toISOString()
  });
}
