export default function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();

  return res.status(200).json({
    presence: "present_high",
    mode: "work",
    focus_active: false,
    phones_connected: 1,
    cloud_mode: true,
    hub: "Vercel Edge Cloud",
    confidence: 0.98,
    timestamp: new Date().toISOString()
  });
}
