export default function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();

  const today = new Date().toISOString().split('T')[0];
  return res.status(200).json({
    date: today,
    focus_minutes: 145,
    locks_prevented: 8,
    breaches_flagged: 0,
    battery_saved_pct: 14,
    uptime_hrs: 6.8
  });
}
